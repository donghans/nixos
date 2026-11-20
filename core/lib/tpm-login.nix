# TPM+PIN 으로 부팅한 직후 greetd 로그인·gnome-keyring 을 비밀번호 입력 없이 여는 NixOS 설정 조각 (plan/boot-doctor-keyring §11-B).
# luks mod(mods/sys/services/tpm-login.nix)와 VM 시험(core/scripts/tests/vm/sb-pcrlock.nix 의 tpmlogin)이 같은 것을 쓴다 — 시험이 실제 설정을 그대로 검증하게.
# 반환값은 NixOS 설정 attrset 이다(모듈 함수가 아님): `import ./tpm-login.nix { inherit lib pkgs config; user = "alice"; }`.
#
# 설계 한 줄: 부팅 때 입력한 TPM PIN 은 **로그인 비밀번호로 쓰이지 않는다**. PIN 은 TPM 에 봉인해 둔 별도의 강한 비밀번호 P 를 푸는 열쇠일 뿐이고,
# PAM 은 P 가 담긴 새 키(login-pw)만 읽는다. PIN 캐시(luks2-pin)는 PAM 이 보지 않으며 서비스가 어떤 경로로 끝나든 지운다.
#
# 각 항목이 필요한 이유(VM 시험으로 확인):
#  - 서비스는 KeyringMode=shared 여야 캐시된 PIN 을 읽을 수 있다(private 이면 Permission denied).
#  - 키를 덮어쓰면(padd 갱신) 제한 시간이 사라져 P 가 영구히 남는다 → 덮어쓰지 않고 새 키(login-pw)를 만들며 120초 제한을 건다.
#  - 오입력은 TPM 전체가 공유하는 잠금 카운터를 올려 LUKS 의 TPM 해제까지 잠글 수 있다 → 부팅당 1회만 시도하고, PIN 불일치면 표지를 남겨 다음 부팅부터 시도하지 않는다.
#  - 캐시된 값이 계정 비밀번호와 다르면 pam_unix 가 다시 묻지 않고 실패한다 → 실패 시 캐시를 지우는 PAM 규칙(다음 시도는 평소처럼 비밀번호를 묻는다).
#  - greetd 는 greeter 프로세스(사용자 greeter)도 같은 PAM 서비스의 세션 스택으로 연다 → 세션 단계 삭제는 그 사용자를 건너뛴다(안 그러면 로그인하기도 전에 캐시가 사라진다).
{
  lib,
  pkgs,
  config,
  user, # 봉인된 비밀번호로 로그인할 계정(한 계정)
  greeterUser ? "greeter", # greetd 의 greeter 가 도는 계정(mods/gui/base/greeter.nix)
  service ? "greetd", # PAM 서비스 이름
  cacheSeconds ? 120, # login-pw 가 커널 키링에 머무는 최대 시간
}: let
  keyctl = "${pkgs.keyutils}/bin/keyctl";
  state = "/var/lib/nixseal/pwseal";
  # PIN 캐시·로그인 비밀번호 캐시를 지운다. PAM(pam_exec, root)과 서비스의 ExecStopPost 가 쓴다.
  purge = pkgs.writeShellScript "nixseal-login-purge" ''
    [ "''${PAM_USER:-}" = "${greeterUser}" ] && exit 0
    for k in login-pw luks2-pin; do
      id=$(${keyctl} search @u user "$k" 2>/dev/null) && ${keyctl} unlink "$id" @u >/dev/null 2>&1
    done
    exit 0
  '';
  removePin = pkgs.writeShellScript "nixseal-pin-purge" ''
    id=$(${keyctl} search @u user luks2-pin 2>/dev/null) && ${keyctl} unlink "$id" @u >/dev/null 2>&1
    exit 0
  '';
  unseal = pkgs.writeShellScript "nixseal-pwunseal" ''
    export PATH=${lib.makeBinPath [pkgs.coreutils pkgs.gnugrep pkgs.keyutils pkgs.tpm2-tools pkgs.openssl]}
    export TPM2TOOLS_TCTI=device:/dev/tpmrm0
    user=${user}
    state=${state}
    log() { echo "nixseal-pwunseal: $*"; }

    pin_id=$(keyctl search @u user luks2-pin 2>/dev/null) || { log "부팅 PIN 캐시가 없다(복구 암호·FIDO2 로 부팅했거나 이미 만료) — 평소 로그인"; exit 0; }
    # PIN 은 변수로만 다룬다(명령줄·환경변수·파일에 남기지 않는다). 어떤 경로로 끝나든 PIN 캐시는 지운다.
    pin=$(keyctl pipe "$pin_id") && [ -n "$pin" ] || { log "부팅 PIN 캐시를 읽지 못했다(KeyringMode 문제?) — 평소 로그인"; keyctl unlink "$pin_id" @u >/dev/null 2>&1; exit 0; }
    work=""
    cleanup() { keyctl unlink "$pin_id" @u >/dev/null 2>&1; unset pin; [ -n "$work" ] && rm -rf "$work"; }
    trap cleanup EXIT

    [ -r "$state/$user.pub" ] && [ -r "$state/$user.priv" ] || { log "봉인된 비밀번호가 없다($state/$user.*) — 평소 로그인. 만들려면 nixseal pw seal"; exit 0; }
    if [ -e "$state/$user.failed" ]; then
      log "이전 실패 표지($(cat "$state/$user.failed")) — TPM 잠금 카운터를 더 올리지 않으려고 이번 부팅은 시도하지 않는다. 풀려면 nixseal pw seal"
      exit 0
    fi
    [ -e /dev/tpmrm0 ] || { log "TPM 장치가 없다 — 평소 로그인"; exit 0; }

    work=$(mktemp -d /run/nixseal-pw.XXXXXX) && chmod 700 "$work" || exit 0
    tpm2_createprimary -C o -c "$work/prim.ctx" -G ecc256:aes128cfb -a 'restricted|decrypt|fixedtpm|fixedparent|sensitivedataorigin|userwithauth|noda' >/dev/null 2>&1 \
      || { log "TPM 의 부모 키를 만들지 못했다 — 평소 로그인"; exit 0; }
    tpm2_load -C "$work/prim.ctx" -u "$state/$user.pub" -r "$state/$user.priv" -c "$work/seal.ctx" >/dev/null 2>&1 \
      || { log "봉인 블롭을 TPM 에 올리지 못했다(TPM 초기화나 블롭 손상) — 평소 로그인. 다시 봉인: nixseal pw seal"; exit 0; }
    tpm2_startauthsession --hmac-session -S "$work/sess.ctx" >/dev/null 2>&1 || { log "TPM 암호화 세션을 만들지 못했다 — 평소 로그인"; exit 0; }
    # 인증값 = SHA-256(PIN) (길이·문자 제한을 없애려고). 부팅당 정확히 한 번만 시도한다.
    err=$(printf '%s' "$pin" | openssl dgst -sha256 -binary | tpm2_unseal -c "$work/seal.ctx" -p "session:$work/sess.ctx+file:-" -o "$work/p.out" 2>&1) \
      || {
        if printf '%s' "$err" | grep -q "authorization HMAC check failed"; then
          echo "bad-pin $(date -Iseconds)" > "$state/$user.failed"
          log "PIN 이 봉인할 때의 PIN 과 다르다(TPM 잠금 카운터가 1 올랐다) — 평소 로그인. PIN 을 바꿨다면 nixseal pw seal 을 다시"
        elif printf '%s' "$err" | grep -q "DA lockout"; then
          log "TPM 이 오입력 잠금 상태다 — 평소 로그인(카운터는 오르지 않았다)"
        else
          log "TPM 해제 실패 — 평소 로그인: $(printf '%s' "$err" | tail -1)"
        fi
        exit 0
      }
    pw=$(cat "$work/p.out"); rm -f "$work/p.out"
    [ -n "$pw" ] || { log "봉인된 값이 비어 있다 — 평소 로그인"; exit 0; }
    # 봉인한 값이 지금도 계정 비밀번호인지 확인(passwd 로 바꾼 뒤라면 일치하지 않는다 — 그대로 PAM 에 주면 매 부팅 첫 시도가 실패한다)
    if ! printf '%s\0' "$pw" | /run/wrappers/bin/unix_chkpwd "$user" nullok; then
      echo "stale $(date -Iseconds)" > "$state/$user.failed"
      log "봉인된 비밀번호가 지금의 계정 비밀번호와 다르다 — 평소 로그인. 계정 비밀번호를 바꿨다면 nixseal pw seal 을 다시"
      unset pw; exit 0
    fi
    printf '%s' "$pw" | keyctl padd user login-pw @u >/dev/null
    unset pw
    id=$(keyctl search @u user login-pw) && keyctl setperm "$id" 0x3f010000 && keyctl timeout "$id" ${toString cacheSeconds}
    log "봉인된 비밀번호를 풀어 login-pw 로 두었다(${toString cacheSeconds}초). 부팅 PIN 캐시는 지웠다"
  '';
  pamExec = "${pkgs.linux-pam}/lib/security/pam_exec.so";
  ruleOrder = rules: name: offset: config.security.pam.services.${service}.rules.${rules}.${name}.order + offset;
in {
  systemd.services.nixseal-pwunseal = {
    description = "Unseal the login password with the boot PIN (TPM) for greetd";
    wantedBy = ["multi-user.target"];
    # greetd 보다 먼저 끝나게 순서만 정한다. Requires 는 쓰지 않는다 — 이 서비스가 실패하거나 느려도 로그인 화면은 막지 않는다(평소 비밀번호 입력으로 돌아간다).
    before = ["greetd.service" "display-manager.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      KeyringMode = "shared"; # 캐시된 PIN(root 사용자 키링)을 읽으려면 필요(private 이면 거부됨)
      TimeoutStartSec = "30s";
      ExecStart = unseal;
      ExecStopPost = "-${removePin}"; # 서비스가 죽거나 시간 초과여도 PIN 캐시를 남기지 않는다
    };
  };
  security.pam.services.${service} = {
    # (1) auth 맨 앞: 풀어 둔 비밀번호(login-pw)만 PAM authtok 으로 — 부팅 PIN(luks2-pin)은 PAM 이 보지 않는다
    rules.auth.systemd_loadkey = {
      order = ruleOrder "auth" "unix-early" (-10);
      control = "optional";
      modulePath = "${config.systemd.package}/lib/security/pam_systemd_loadkey.so";
      settings.keyname = "login-pw";
    };
    # (2) unix(sufficient)가 실패해야만 닿는 자리: 불일치면 캐시를 지운다 → 이번 시도는 실패하지만 다음 시도는 평소처럼 비밀번호를 묻는다
    rules.auth.nixseal_purge_on_fail = {
      order = ruleOrder "auth" "unix" 10;
      control = "optional";
      modulePath = pamExec;
      args = ["quiet" "${purge}"];
    };
    # (3) 세션이 열린 직후: 캐시를 지워 사용자 세션 프로세스가 보지 못하게 한다(greeter 사용자는 건너뜀)
    rules.session.nixseal_purge = {
      order = ruleOrder "session" "gnome_keyring" 10;
      control = "optional";
      modulePath = pamExec;
      args = ["quiet" "${purge}"];
    };
  };
}
