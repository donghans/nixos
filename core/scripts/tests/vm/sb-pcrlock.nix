# Secure Boot + lanzaboote UKI + swtpm 위에서 「TPM2+PIN(pcrlock) 으로 LUKS 를 푸는」 흐름을 재현하는 NixOS VM 시험.
# 쓰는 곳: S6(TPM+PIN) 의 설계 근거 시험, 이후 nixseal tpm / recover 의 VM 시험 틀. 실행은 ./default.nix 의 주석 참고.
#
# 시나리오(scenario):
#   positive … A(등록 직후 PIN 으로 열림) → C(dbx 를 바꾸고 「재부팅 전에」 정책 갱신 → PIN 으로 열림)
#   negative … A → B(dbx 만 바꾸고 갱신 안 함 → TPM 이 거부) → D1(그 상태에선 정책 갱신도 거부됨)
#              → D2(remove-policy + 복구 암호로 재등록 → PIN 으로 열림)
#   esp      … E1·E2(ESP 를 포맷·재생성, credential 만 없어짐)
#   tpmlogin … TPM 에 봉인한 계정 비밀번호 P 를 부팅 PIN 으로 풀어 greetd 로그인·키링을 비밀번호 없이 여는 흐름(core/lib/tpm-login.nix) — PIN 은 PAM 에 닿지 않는다(S0·T1~T7)
#   doctor   … `nixseal doctor` 가 실제 장치·TPM·펌웨어에서 선언과 어긋남을 잡는다(X1~X8). 기준선 A 뒤에 재부팅 없이 진행(plan/boot-doctor-keyring)
#
# 이 틀이 제대로 돌려면 필요한 것(시행착오로 확인 — 빠뜨리면 조용히 실패한다; 해당 설정은 core/lib/luks-tpm2.nix 에 있고 luks mod 와 공유):
#   - lanzaboote 스텁이 ESP 의 \loader\credentials\pcrlock.*.cred 를 initrd 로 넘긴다. 그 파일은 `make-policy` 가 쓴다.
#     재부팅(crash) 전에 반드시 sync — vfat ESP 라 안 하면 파일이 사라져 「Couldn't find pcrlock policy」가 난다.
#   - initrd 에 systemd-pcrphase-initrd·systemd-pcrosseparator 를 켜야 이벤트 로그에 750-enter-initrd·750-os-separator 가 생기고,
#     그래야 make-policy 가 PCR 7 을 보호 대상에 남긴다(없으면 PCR 7 이 조용히 빠져 PCR 15 만 남는다 — 보호가 사실상 없음).
#   - 루트가 영구(persistentRoot)여야 한다: /var/lib/systemd/pcrlock.json(NV 인덱스 정보)이 재부팅 뒤에도 있어야 정책 갱신이 같은 NV 를 쓴다.
#   - machine-id 를 고정: credential 파일 이름이 pcrlock.<machine-id>.cred 라서 부팅마다 바뀌면 옛 파일이 쌓인다.
#   - OVMF 는 dbx 쓰기를 한 번만 반영한다(두 번째 쓰기는 종료 코드 0 이지만 무시됨). 그래서 시나리오당 dbx 변경은 한 번.
{
  pkgs,
  lz,
  scenario,
  ...
}: let
  common = "${lz}/nix/tests/lanzaboote/common";
  pcrlock = "${pkgs.systemd}/lib/systemd/systemd-pcrlock";
  # doctor 시나리오: 실제 nixseal(ISO 와 같은 래퍼)로 시험한다
  nixseal = import ../../../lib/nixseal-iso.nix {
    inherit pkgs;
    script = ../../nixseal.py;
  };
in {
  name = "sb-pcrlock-${scenario}";

  nodes.machine = {
    config,
    pkgs,
    lib,
    ...
  }: {
    lanzabooteTest.persistentRoot = true;
    boot.initrd.systemd.enable = true;
    virtualisation.tpm.enable = true;
    virtualisation.emptyDiskImages = [64];
    environment.systemPackages =
      [pkgs.cryptsetup pkgs.tpm2-tools pkgs.efitools pkgs.openssl pkgs.dosfstools]
      ++ lib.optionals (scenario == "doctor" || scenario == "positive") [nixseal pkgs.jq]
      ++ lib.optionals (scenario == "tpmlogin") [nixseal pkgs.keyutils pkgs.gnome-keyring pkgs.libsecret pkgs.dbus pkgs.tpm2-tools];

    # 데이터 볼륨(/dev/vdb)을 initrd 에서 TPM+PIN 으로 연다. 열리지 않아도 부팅은 계속(nofail).
    boot.initrd.luks.devices.cryptdata = {
      device = "/dev/vdb";
      crypttabExtraOpts = ["tpm2-device=auto" "nofail" "tries=1" "timeout=30s"];
    };
    fileSystems."/data" = {
      device = "/dev/mapper/cryptdata";
      fsType = "ext4";
      options = ["nofail" "x-systemd.device-timeout=30s"];
    };

    # ── tpmlogin 시나리오: 사용자·greetd(실제 설정은 core/lib/tpm-login.nix — mods/sys/services/tpm-login.nix 와 같은 파일) ──
    # 계정 비밀번호 P(강한 값)를 TPM 에 봉인하고, 부팅 PIN(1234)으로 풀어 로그인·키링을 연다. PIN 은 로그인 비밀번호가 아니다.
    users.users.alice = lib.mkIf (scenario == "tpmlogin") {
      isNormalUser = true;
      uid = 1000;
      password = "S3cure-Account-Pass!";
    };
    services.gnome.gnome-keyring.enable = lib.mkIf (scenario == "tpmlogin") true;
    environment.etc."krgreeter.py" = lib.mkIf (scenario == "tpmlogin") {
      text = ''
        import json, os, socket, struct, sys, time
        s = socket.socket(socket.AF_UNIX); s.connect(os.environ["GREETD_SOCK"])
        log = open("/tmp/greeter.log", "a"); log.write("RUN-START\n")
        def send(m):
            b = json.dumps(m).encode(); s.sendall(struct.pack("=I", len(b)) + b)
        def recv():
            n = struct.unpack("=I", s.recv(4))[0]; d = b""
            while len(d) < n: d += s.recv(n - len(d))
            return json.loads(d)
        user = sys.argv[1]
        pw = open("/tmp/kr-greeter-pw").read()   # 프롬프트가 나오면 이 값으로 응답한다(시험이 정한다)
        send({"type": "create_session", "username": user})
        prompted = False; result = "?"
        while True:
            r = recv(); log.write(json.dumps(r) + "\n"); log.flush()
            if r["type"] == "auth_message":
                prompted = True
                send({"type": "post_auth_message_response", "response": pw})
            elif r["type"] == "success":
                send({"type": "start_session", "cmd": ["/etc/kr-probe.sh"], "env": []}); r2 = recv(); log.write(json.dumps(r2) + "\n"); result = "SESSION-STARTED"; break
            else:
                result = "AUTH-FAILED"; send({"type": "cancel_session"}); break
        log.write("RESULT prompted=%s result=%s\n" % (prompted, result)); log.close()
        time.sleep(1)
      '';
    };
    # 로그인한 사용자 세션 안에서: 부팅 PIN 캐시·풀어 둔 비밀번호가 보이나, 키링이 열려 있나
    environment.etc."kr-probe.sh" = lib.mkIf (scenario == "tpmlogin") {
      mode = "0755";
      text = ''
        #!/bin/sh
        {
          echo "RUN-START"
          for k in luks2-pin login-pw; do
            if id=$(${pkgs.keyutils}/bin/keyctl search @s user $k 2>&1); then echo "SESSION-SEES $k"; else echo "SESSION-DOES-NOT-SEE $k"; fi
          done
          # PAM 이 띄운 gnome-keyring 은 alice 의 systemd 사용자 버스에 비밀 서비스를 올린다 — 그 버스로 직접 조회한다(세션이 끝나면 데몬도 끝나므로 세션 안에서)
          export XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus
          echo "LOOKUP-IN-SESSION: $(timeout 20 ${pkgs.libsecret}/bin/secret-tool lookup k v 2>&1 | tr '\n' ' ')"
          echo "PROBE-DONE"
        } >> /tmp/kr-probe.out 2>&1
      '';
    };
    services.greetd = lib.mkIf (scenario == "tpmlogin") {
      enable = true;
      settings.default_session = {
        command = "${pkgs.python3}/bin/python3 /etc/krgreeter.py alice";
        user = "greeter"; # 실제 구성(mods/gui/base/greeter.nix)과 같다 — greeter 는 로그인할 사용자와 다른 계정으로 돈다
      };
    };
    # greetd 는 graphical.target 에 묶여 부팅 때 자동 시작된다 — 시험이 직접 시작하도록 막는다(안 그러면 greeter 가 먼저 캐시로 로그인한다)
    systemd.services.greetd.wantedBy = lib.mkIf (scenario == "tpmlogin") (lib.mkForce []);
    systemd.defaultUnit = lib.mkIf (scenario == "tpmlogin") (lib.mkForce "multi-user.target");
    security.pam.services.greetd = lib.mkIf (scenario == "tpmlogin") {enableGnomeKeyring = true;};
    # T6 시험 전용: 이 파일이 있으면 서비스가 아예 돌지 않는다(서비스 실패·크래시·의존 실패를 흉내 — NixOS 의 /etc 가 읽기 전용이라 systemctl mask 는 쓸 수 없다)
    systemd.services.nixseal-pwunseal.unitConfig.ConditionPathExists = lib.mkIf (scenario == "tpmlogin") "!/var/lib/test-skip-pwunseal";

    # initrd 의 pcrphase 유닛·모듈·정책 불일치 경고는 실제 설정(luks mod)과 같은 파일을 쓴다 — 시험이 실제 설정을 검증하도록
    imports = [
      "${common}/lanzaboote.nix"
      ({
        config,
        pkgs,
        lib,
        ...
      }: {
        config = lib.mkIf (scenario == "tpmlogin") (import ../../../lib/tpm-login.nix {
          inherit lib pkgs config;
          user = "alice";
        });
      })
      ({
        config,
        pkgs,
        lib,
        ...
      }:
        import ../../../lib/luks-tpm2.nix {
          inherit lib pkgs config;
          name = "cryptdata";
        })
    ];

    environment.etc.machine-id.text = "0123456789abcdef0123456789abcdef\n";
    # dbx 를 바꿀 때 서명에 쓰는 시험용 KEK(lanzaboote 시험 고정 키)
    # E1: ESP 를 비운 뒤 부트로더(서명된 UKI)를 다시 만드는 명령 — 업스트림 image.nix 가 ESP 를 만들 때와 같은 호출
    environment.etc."esp-install".text = "${config.boot.lanzaboote.installCommand} --public-key /var/lib/lanzaboote-test-fixture/keys/db/db.pem --private-key /var/lib/lanzaboote-test-fixture/keys/db/db.key /boot /nix/var/nix/profiles/system-1-link\n";
    environment.etc."test-kek".source = "${lz}/nix/tests/fixtures/uefi-keys/keys/KEK";
  };

  testScript = {nodes, ...}:
    (import "${common}/image-helper.nix" {inherit (nodes) machine;})
    + ''
      KEK = "/etc/test-kek"
      DBX = "/sys/firmware/efi/efivars/dbx-d719b2cb-3d3a-4596-a3bc-dad00e67656f"

      def pcr_refresh(force=False):
          # 현재 EFI 변수로 「다음 부팅」의 PCR 7 을 예측해 정책(NV·ESP 의 credential)을 갱신한다.
          # 예측이 현재 정책과 같으면 make-policy 는 아무 것도 안 하고(ESP 의 credential 도 안 씀) 끝난다 — 비운 ESP 를 되살리려면 --force.
          for sub in ["lock-secureboot-policy", "lock-secureboot-authority", "make-policy" + (" --force" if force else "")]:
              machine.succeed("${pcrlock} " + sub + " 2>&1")
          machine.succeed("sync")

      def nixseal_refresh(force=False):
          # 실제 도구(nixseal)로 정책을 갱신한다 — 바꾸기 전 상태를 변종으로 보존해 dbx 변경 직후 재부팅 전에도 PCR 7 이 남는다.
          # 정책에 PCR 7 이 남았는지도 확인한다: 빠져 있으면 재부팅 시험이 「PIN 으로 열림」으로 통과해 버리는 빈 통과가 되기 때문이다(2026-11-20 에 발견: 변종 없이 갱신하면 PCR 7 이 조용히 빠진다).
          machine.succeed("printf '내가 한 변경\\n' | nixseal tpm refresh-policy" + (" --force" if force else "") + " 2>&1")
          machine.succeed("grep -q '\"pcr\":7' /var/lib/systemd/pcrlock.json")
          machine.succeed("sync")

      def reboot():
          machine.succeed("sync")   # ESP(vfat) 의 credential 이 디스크에 내려가야 한다
          machine.crash()
          machine.start()

      def unlock_with_pin():
          machine.wait_for_console_text("PIN")
          machine.send_console("1234\n")

      def data_mounted():
          return machine.execute("mount | grep -q 'cryptdata on /data'")[0] == 0

      def dbx_change():
          # 시험용 해시로 dbx 를 만든다(KEK 로 서명한 인증 변수 쓰기). OVMF 는 한 번만 반영한다.
          machine.succeed("cd /tmp && echo 1 > h.bin && hash-to-efi-sig-list h.bin d.esl")
          machine.succeed(f"cd /tmp && sign-efi-sig-list -t '2030-01-01 00:00:01' -k {KEK}/KEK.key -c {KEK}/KEK.pem dbx d.esl d.auth")
          machine.succeed("cd /tmp && efi-updatevar -f d.auth dbx")
          machine.succeed(f"test -e {DBX}")

      machine.wait_for_unit("multi-user.target")
      machine.succeed("echo -n supersecret | cryptsetup luksFormat -q --iter-time=1 /dev/vdb -")
      machine.succeed("echo -n supersecret | cryptsetup luksOpen -q /dev/vdb cryptdata")
      machine.succeed("mkfs.ext4 /dev/mapper/cryptdata; systemctl stop data.mount || true; sleep 1; cryptsetup luksClose cryptdata")
      pcr_refresh()
      out = machine.succeed("${pcrlock} make-policy 2>&1")
      assert "PCR 7 (secure-boot-policy) matches" in out, "PCR 7 이 정책에서 빠졌다:\n" + out
      machine.succeed("PASSWORD=supersecret NEWPIN=1234 systemd-cryptenroll --tpm2-device=auto --tpm2-pcrlock=/var/lib/systemd/pcrlock.json --tpm2-with-pin=yes /dev/vdb 2>&1")

      with subtest("A: 기준선 — 등록 직후 재부팅하면 PIN 만으로 열린다"):
          reboot()
          unlock_with_pin()
          machine.wait_for_unit("multi-user.target")
          machine.wait_until_succeeds("mount | grep -q 'cryptdata on /data'", timeout=60)

      ${
        if scenario == "positive"
        then ''
          with subtest("C: 양성 — dbx 를 바꾼 직후 재부팅 전에 정책을 갱신하면(PCR 7 은 남은 채) PIN 만으로 열린다"):
              dbx_change()
              nixseal_refresh()
              reboot()
              unlock_with_pin()
              machine.wait_for_unit("multi-user.target")
              machine.wait_until_succeeds("mount | grep -q 'cryptdata on /data'", timeout=60)
        ''
        else if scenario == "negative"
        then ''
          with subtest("B: 음성 — dbx 만 바꾸고 정책을 갱신하지 않으면 TPM 이 거부한다"):
              dbx_change()
              reboot()
              unlock_with_pin()
              # 이 문구가 tpmFailWarning 이 잡을 신호다
              machine.wait_for_console_text("does not match current system state")
              machine.wait_for_unit("multi-user.target")
              assert not data_mounted(), "정책 갱신 없이 열렸다"
              # luks.tpmFailWarning 의 경고가 화면(콘솔)과 저널에 나갔다
              machine.succeed("journalctl -b -u tpm-fail-warning | grep -q 'the TPM refused to unlock this disk'")

          with subtest("D1: B 이후에는 옛 정책을 만족하지 못해 정책 갱신(make-policy)도 거부된다"):
              status, out = machine.execute("${pcrlock} lock-secureboot-policy 2>&1 && ${pcrlock} lock-secureboot-authority 2>&1 && ${pcrlock} make-policy 2>&1")
              assert status != 0, "B 이후인데 make-policy 가 성공했다:\n" + out

          with subtest("D2: 복구 — remove-policy 후 복구 암호로 TPM 슬롯을 다시 등록하면 PIN 으로 열린다"):
              machine.succeed("${pcrlock} remove-policy 2>&1")
              pcr_refresh()
              machine.succeed("PASSWORD=supersecret NEWPIN=1234 systemd-cryptenroll --wipe-slot=tpm2 --tpm2-device=auto --tpm2-pcrlock=/var/lib/systemd/pcrlock.json --tpm2-with-pin=yes /dev/vdb 2>&1")
              reboot()
              unlock_with_pin()
              machine.wait_for_unit("multi-user.target")
              machine.wait_until_succeeds("mount | grep -q 'cryptdata on /data'", timeout=60)
        ''
        else if scenario == "tpmlogin"
        then ''
          PW = "S3cure-Account-Pass!"      # 계정 비밀번호 P(강한 값) — 부팅 PIN(1234)과 다르다
          fails = []

          def soft(name, cond):
              print(("RESULT OK   " if cond else "RESULT FAIL ") + name)
              if not cond:
                  fails.append(name)

          def keys():
              return machine.succeed("cat /proc/keys")

          def has_key(name):
              return any(name in l for l in keys().splitlines())

          def counter():
              out = machine.succeed("export TPM2TOOLS_TCTI=device:/dev/tpmrm0; tpm2_getcap properties-variable | grep LOCKOUT_COUNTER")
              return int(out.split("0x")[1].strip(), 16)

          def boot_with_pin():
              reboot()
              unlock_with_pin()
              machine.wait_for_unit("multi-user.target")
              machine.wait_until_succeeds("systemctl is-active nixseal-pwunseal || test -e /var/lib/test-skip-pwunseal", timeout=60)
              machine.wait_until_succeeds("mount | grep -q 'cryptdata on /data'", timeout=60)
              machine.wait_for_unit("user@1000.service")

          def kr_prep(password):
              # 로그인 키링을 이 비밀번호로 만들고 항목 하나를 넣는다(alice 의 사용자 세션 버스에서)
              out = machine.succeed("su alice -s /bin/sh -c \"export XDG_RUNTIME_DIR=/run/user/1000; dbus-run-session -- sh -c 'echo -n " + password + " | gnome-keyring-daemon --daemonize --login; eval \\$(gnome-keyring-daemon --start --components=secrets); echo secretval | secret-tool store --label=t k v; secret-tool lookup k v'\" 2>&1")
              assert "secretval" in out, out
              machine.execute("pkill -x gnome-keyring-d || true; sleep 1; rm -f /run/user/1000/keyring/*")

          def login(label, greeter_pw=PW):
              # 진짜 greetd 에 greeter 로 로그인을 시도하고 (프롬프트·결과·세션 안 키 가시성·키링 열림)을 기록한다. greetd 는 세션이 끝나면 greeter 를 다시 띄운다 → 첫 실행 블록만 본다.
              # 주의: 이 드라이버는 명령을 set -e 로 실행한다 — 일치 없는 pkill 은 || true 가 필수다.
              machine.execute("systemctl stop greetd || true; sleep 1; pkill -u greeter || true; pkill -x gnome-keyring-d || true; rm -f /run/user/1000/keyring/* /tmp/greeter.log /tmp/kr-probe.out")
              machine.succeed("printf '%s' '" + greeter_pw + "' > /tmp/kr-greeter-pw; chmod 644 /tmp/kr-greeter-pw")
              machine.succeed("systemctl start greetd")
              machine.execute("for i in $(seq 1 60); do grep -q RESULT /tmp/greeter.log 2>/dev/null && grep -q PROBE-DONE /tmp/kr-probe.out 2>/dev/null && break; grep -q AUTH-FAILED /tmp/greeter.log 2>/dev/null && break; sleep 1; done; sleep 2")
              g = machine.execute("awk '/RUN-START/{n++} n==1' /tmp/greeter.log 2>&1")[1]
              pr = machine.execute("awk '/RUN-START/{n++} n==1' /tmp/kr-probe.out 2>&1")[1]
              print("=== " + label + " ===\n" + g + "\n" + pr)
              machine.execute("systemctl stop greetd || true; pkill -x gnome-keyring-d || true; sleep 1; rm -f /run/user/1000/keyring/*")
              return g, pr

          with subtest("S0: 봉인 — PIN(1234)·계정 비밀번호 P 를 받아 TPM 에 봉인하고, 틀린 계정 비밀번호는 거부한다"):
              machine.succeed("loginctl enable-linger alice")
              machine.wait_for_unit("user@1000.service")
              st, out = machine.execute("printf '1234\\nwrong-password\\n' | nixseal pw seal --user alice --stdin 2>&1")
              soft("S0-1 틀린 계정 비밀번호는 봉인을 거부한다", st != 0 and "현재 비밀번호와 다르다" in out and not machine.execute("ls /var/lib/nixseal/pwseal/alice.pub")[0] == 0)
              machine.succeed("printf '1234\\n" + PW + "\\n' | nixseal pw seal --user alice --stdin 2>&1")
              machine.succeed("ls -l /var/lib/nixseal/pwseal/")
              soft("S0-2 블롭 권한 0600", machine.succeed("stat -c %a /var/lib/nixseal/pwseal/alice.priv").strip() == "600")
              kr_prep(PW)   # 키링 비밀번호도 P

          with subtest("T1: 봉인 뒤 TPM+PIN 부팅 — PIN 은 PAM 에 닿지 않고, P 가 프롬프트 없이 로그인·키링을 연다"):
              boot_with_pin()
              print(machine.succeed("journalctl -b -u nixseal-pwunseal --no-pager 2>&1 | tail -6"))
              soft("T1-1 서비스가 P 를 풀어 login-pw 로 두었다", "login-pw 로 두었다" in machine.succeed("journalctl -b -u nixseal-pwunseal --no-pager"))
              soft("T1-2 부팅 PIN 캐시(luks2-pin)는 지워졌다", not has_key("luks2-pin"))
              soft("T1-3 login-pw 가 캐시돼 있고 제한 시간이 있다", any("login-pw" in l and " 2m " in l or "login-pw" in l and " 1m " in l for l in keys().splitlines()))
              machine.succeed("keyctl link @u @s")
              cached = machine.succeed("keyctl pipe $(keyctl search @u user login-pw)")
              soft("T1-4 login-pw 의 내용은 P 이고 PIN 이 아니다", cached == PW and cached != "1234")
              machine.succeed("keyctl unlink @u @s")
              g, pr = login("T1")
              soft("T1-5 프롬프트 없이 로그인", "prompted=False" in g and "SESSION-STARTED" in g)
              soft("T1-6 키링이 비밀번호 입력 없이 열려 있다", "LOOKUP-IN-SESSION: secretval" in pr)
              soft("T1-7 로그인한 사용자 세션에서 PIN 캐시·login-pw 가 보이지 않는다", "SESSION-DOES-NOT-SEE luks2-pin" in pr and "SESSION-DOES-NOT-SEE login-pw" in pr)
              soft("T1-8 로그인 뒤 두 캐시 모두 남아 있지 않다", not has_key("login-pw") and not has_key("luks2-pin"))

          with subtest("T2: 캐시 없음(만료·이미 사용) — 프롬프트가 나오고 P 를 입력하면 로그인·키링이 열린다. PIN 은 거부된다"):
              g, pr = login("T2")
              soft("T2-1 프롬프트가 나오고 P 로 통과", "prompted=True" in g and "SESSION-STARTED" in g)
              soft("T2-2 입력한 P 로 키링이 열린다", "LOOKUP-IN-SESSION: secretval" in pr)
              g, pr = login("T2b", greeter_pw="1234")
              soft("T2-3 부팅 PIN(1234)으로는 로그인되지 않는다", "AUTH-FAILED" in g and "SESSION-STARTED" not in g)

          with subtest("T3: 봉인이 없으면 — 서비스는 PIN 캐시를 지우고 평소 프롬프트(PIN 이 PAM 에 닿지 않는다)"):
              machine.succeed("nixseal pw remove --user alice --yes 2>&1")
              boot_with_pin()
              soft("T3-1 PIN 캐시가 지워졌고 login-pw 는 없다", not has_key("luks2-pin") and not has_key("login-pw"))
              g, pr = login("T3")
              soft("T3-2 평소 프롬프트로 P 입력 → 로그인", "prompted=True" in g and "SESSION-STARTED" in g)

          with subtest("T4: 봉인할 때 PIN 을 잘못 넣었으면 — 해제 실패 표지·TPM 카운터 +1(한 번만)·평소 로그인"):
              machine.succeed("printf '9999\\n" + PW + "\\n' | nixseal pw seal --user alice --stdin 2>&1")
              c0 = counter()
              boot_with_pin()
              c1 = counter()
              soft("T4-1 실패 표지(bad-pin)가 남았다", machine.succeed("cat /var/lib/nixseal/pwseal/alice.failed").startswith("bad-pin"))
              soft("T4-2 TPM 오입력 카운터가 정확히 1 올랐다(" + str(c0) + "→" + str(c1) + ")", c1 == c0 + 1)
              soft("T4-3 PIN 캐시는 지워졌고 login-pw 는 없다", not has_key("luks2-pin") and not has_key("login-pw"))
              boot_with_pin()
              soft("T4-4 다음 부팅은 시도하지 않아 카운터가 더 오르지 않는다", counter() == c1)
              soft("T4-5 표지가 있다는 로그를 남겼다", "이전 실패 표지" in machine.succeed("journalctl -b -u nixseal-pwunseal --no-pager"))
              g, pr = login("T4")
              soft("T4-6 평소 프롬프트로 P 입력 → 로그인", "prompted=True" in g and "SESSION-STARTED" in g)
              machine.succeed("export TPM2TOOLS_TCTI=device:/dev/tpmrm0; tpm2_dictionarylockout --clear-lockout")

          with subtest("T5: 계정 비밀번호를 바꾼 뒤(봉인이 낡음) — stale 표지·평소 프롬프트(로그인이 매 부팅 한 번 실패하지 않는다)"):
              machine.succeed("printf '1234\\n" + PW + "\\n' | nixseal pw seal --user alice --stdin 2>&1")
              machine.succeed("echo 'alice:Another-Password-9' | chpasswd")
              boot_with_pin()
              soft("T5-1 stale 표지가 남았다", machine.succeed("cat /var/lib/nixseal/pwseal/alice.failed").startswith("stale"))
              soft("T5-2 PIN 캐시는 지워졌고 login-pw 는 없다(옛 비밀번호가 PAM 에 가지 않음)", not has_key("luks2-pin") and not has_key("login-pw"))
              g, pr = login("T5", greeter_pw="Another-Password-9")
              soft("T5-3 새 비밀번호를 프롬프트에서 입력하면 로그인(첫 시도 실패 없음)", "prompted=True" in g and "SESSION-STARTED" in g)
              machine.succeed("echo 'alice:" + PW + "' | chpasswd")

          with subtest("T6: 서비스가 아예 안 돌아도 — PIN 캐시가 남아 있어도 PIN 으로는 로그인되지 않는다(PAM 은 login-pw 만 읽는다)"):
              machine.succeed("printf '1234\\n" + PW + "\\n' | nixseal pw seal --user alice --stdin 2>&1")
              machine.succeed("touch /var/lib/test-skip-pwunseal")
              boot_with_pin()
              soft("T6-1 서비스가 안 돌아 PIN 캐시(luks2-pin)가 아직 남아 있다(이 시험의 전제)", has_key("luks2-pin") and not has_key("login-pw"))
              g, pr = login("T6", greeter_pw="1234")
              soft("T6-2 캐시된 PIN(1234)으로는 로그인되지 않는다", "AUTH-FAILED" in g)
              g, pr = login("T6b", greeter_pw=PW)
              soft("T6-3 P 를 직접 입력하면 로그인된다(막히지 않음)", "prompted=True" in g and "SESSION-STARTED" in g)
              # T6c: 계정 비밀번호를 일부러 PIN 과 같게 두어, PAM 이 PIN 캐시(luks2-pin)를 정말 무시하는지 본다(PIN≠P 일 때는 키 이름을 잘못 읽어도 로그인이 안 돼 구분되지 않는다)
              machine.succeed("keyctl link @u @s; printf '1234' | keyctl padd user luks2-pin @u; echo 'alice:1234' | chpasswd")
              soft("T6c-0 PIN 캐시(luks2-pin)를 다시 넣었다", has_key("luks2-pin"))
              g, pr = login("T6c", greeter_pw="wrong-guess")
              soft("T6c-1 계정 비밀번호 = PIN 인데도 PAM 이 PIN 캐시를 쓰지 않아 프롬프트가 나온다(자동 로그인 안 됨)", "prompted=True" in g and "SESSION-STARTED" not in g)
              machine.succeed("echo 'alice:" + PW + "' | chpasswd")
              machine.succeed("rm -f /var/lib/test-skip-pwunseal")

          with subtest("T7: 캐시된 login-pw 가 계정 비밀번호와 다르면 — 첫 시도는 실패하고 캐시가 지워지며 다음 시도는 평소처럼 통과한다"):
              machine.succeed("keyctl link @u @s; printf 'not-the-password' | keyctl padd user login-pw @u")
              soft("T7-0 틀린 값을 캐시에 넣었다", has_key("login-pw"))
              g, pr = login("T7-1")
              soft("T7-1 불일치 시도는 프롬프트 없이 실패한다", "prompted=False" in g and "AUTH-FAILED" in g)
              soft("T7-2 불일치 시도가 캐시를 지웠다", not has_key("login-pw"))
              g, pr = login("T7-3")
              soft("T7-3 다음 시도는 프롬프트가 나오고 통과한다", "prompted=True" in g and "SESSION-STARTED" in g)

          print("RESULT 요약: 실패 =", fails)
          assert not fails, fails
        ''
        else if scenario == "doctor"
        then ''
          def doctor(env, args=""):
              # 선언(nix 래퍼가 주는 값)을 환경변수로 직접 준다. 데이터 볼륨 /dev/vdb 가 LUKS(TPM2 슬롯) 이고 루트(/)는 평문이다.
              st, out = machine.execute("env " + env + " nixseal doctor " + args + " 2>&1")
              print("doctor[" + env + "] rc=" + str(st) + "\n" + out)
              return st, out

          BASE = "NIXSEAL_DECL_SB=1 NIXSEAL_DECL_TPM2=1 NIXSEAL_DECL_FIDO2=0 NIXSEAL_DECL_LUKS_DEV=/dev/vdb"   # luks(루트) 선언은 안 줌 = 모름 → 루트 칸은 건너뜀

          with subtest("X-: 정책을 nixseal 로 한 번 갱신해 그 시점의 Secure Boot 지문을 기록한다(doctor 의 갱신 누락 검사 전제)"):
              machine.succeed("printf '내가 한 변경\\n' | nixseal tpm refresh-policy --force 2>&1")
              machine.succeed("test -s /var/lib/nixseal/sb-fingerprint")

          with subtest("X0: 기준선 — 슬롯·정책(PCR 7)·credential·펌웨어 SB 가 정상이면 FAIL·WARN 없이 종료 0"):
              st, out = doctor(BASE)
              assert st == 0, out
              assert "[OK] TPM2 슬롯 있음" in out and "PCR 7" in out, out
              assert "[OK] 펌웨어 Secure Boot 켜짐" in out, out
              assert "지문 일치" in out, out
              assert "[FAIL]" not in out and "[WARN]" not in out, out

          with subtest("X1: luks 를 선언했는데 루트(/)는 암호화 장치가 아니다 → FAIL, 종료 1"):
              st, out = doctor(BASE + " NIXSEAL_DECL_LUKS=cryptroot")
              assert st == 1 and "[FAIL] luks 를 선언했는데" in out, out

          with subtest("X1b: luks 없음을 선언했고 루트도 평문이면 FAIL 이 아니다"):
              st, out = doctor("NIXSEAL_DECL_LUKS= NIXSEAL_DECL_SB=1")
              assert st == 0 and "[FAIL]" not in out, out

          with subtest("X3: TPM2 슬롯이 있는데 tpm2 를 선언하지 않았다 → WARN(종료는 0)"):
              st, out = doctor("NIXSEAL_DECL_SB=1 NIXSEAL_DECL_TPM2=0 NIXSEAL_DECL_LUKS_DEV=/dev/vdb")
              assert st == 0 and "[WARN] TPM2 슬롯이 있는데 tpm2 를 선언하지 않았다" in out, out

          with subtest("X4: secure-boot 를 선언하지 않았는데 펌웨어 Secure Boot 가 켜져 있다 → FAIL"):
              st, out = doctor("NIXSEAL_DECL_SB=0")
              assert st == 1 and "[FAIL] secure-boot 를 선언하지 않았는데" in out, out

          with subtest("X5: 정책 파일에서 PCR 7 이 빠졌다 → FAIL(조용한 약화)"):
              machine.succeed("jq '.pcrValues |= map(select(.pcr != 7))' /var/lib/systemd/pcrlock.json > /tmp/pcrlock-no7.json")
              st, out = doctor(BASE + " NIXSEAL_PCRLOCK_JSON=/tmp/pcrlock-no7.json")
              assert st == 1 and "PCR 7(Secure Boot 정책)을 보호하지 않는다" in out, out

          with subtest("X6: ESP 에 정책 credential 이 없다 → FAIL"):
              machine.succeed("mkdir -p /tmp/emptycred")
              st, out = doctor(BASE + " NIXSEAL_ESP_CRED=/tmp/emptycred")
              assert st == 1 and "credential" in out and "[FAIL]" in out, out

          with subtest("X9: dbx 를 바꿨는데 정책을 갱신하지 않으면 FAIL(가장 흔한 사고) — 할 일 안내 포함, nixseal 로 갱신하면 해소"):
              dbx_change()
              st, out = doctor(BASE)
              assert st == 1 and "[FAIL] 정책을 마지막으로 만든 뒤 Secure Boot 키·dbx 가 바뀌었다" in out and "재부팅 전에" in out and "→ 할 일:" in out, out
              nixseal_refresh()   # 바꾸기 전 상태를 변종으로 남기므로 PCR 7 이 정책에 남는다(함수가 확인)
              st, out = doctor(BASE)
              assert st == 0 and "지문 일치" in out and "[FAIL]" not in out, out

          with subtest("X10: ESP(/boot)가 마운트되어 있지 않으면 credential 을 「없음」(FAIL)이 아니라 「확인 못함」(INFO)으로 — mount 안내"):
              machine.succeed("umount /boot")
              st, out = doctor(BASE)
              machine.succeed("mount /boot")
              assert st == 0 and "[INFO] ESP(/boot)가 마운트되어 있지 않아" in out and "sudo mount /boot" in out and "[FAIL]" not in out, out

          with subtest("X7: 정책(pcrlock.json)을 지우면(remove-policy) 슬롯만 남아 FAIL"):
              machine.succeed("${pcrlock} remove-policy 2>&1")
              st, out = doctor(BASE)
              assert st == 1 and "[FAIL] TPM2 슬롯이 있는데 pcrlock 정책 파일을 읽지 못했다" in out, out

          with subtest("X8: TPM2 슬롯이 없고 tpm2 를 선언했다 → INFO(등록 안내), FAIL 아님"):
              machine.succeed("PASSWORD=supersecret systemd-cryptenroll --wipe-slot=tpm2 /dev/vdb 2>&1")
              st, out = doctor(BASE)
              assert st == 0 and "[INFO] tpm2 를 선언했지만 TPM2 슬롯이 아직 없다" in out and "[FAIL]" not in out, out

          with subtest("X11: 슬롯이 없는데 정책 파일(NV)만 남으면 WARN — remove-policy 안내"):
              pcr_refresh()   # make-policy 가 정책 파일을 다시 만든다(슬롯은 X8 에서 지웠다)
              st, out = doctor(BASE)
              assert st == 0 and "[WARN] pcrlock 정책(NV 인덱스)은 남아 있는데 TPM2 슬롯이 없다" in out and "systemd-pcrlock remove-policy" in out, out
        ''
        else ''
          with subtest("E1: ESP 를 같은 라벨·볼륨 ID 로 포맷하고 부트로더를 재생성한 뒤 정책을 다시 만들면 PIN 으로 열린다"):
              # nixseal recover 와 같은 방식: 기존 라벨·볼륨 ID 를 읽어 두고, 내리고, 같은 값으로 포맷하고, 다시 마운트
              info = machine.succeed("blkid -o export /dev/vda1")
              label = [l.split("=", 1)[1] for l in info.splitlines() if l.startswith("LABEL=")]
              volid = [l.split("=", 1)[1] for l in info.splitlines() if l.startswith("UUID=")][0].replace("-", "")
              machine.succeed("umount /boot")
              machine.succeed("mkfs.vfat -F 32 " + ("-n " + label[0] + " " if label else "") + "-i " + volid + " /dev/vda1")
              machine.succeed("mount /boot")
              machine.succeed("test -z \"$(ls -A /boot)\"")
              assert ("UUID=" + volid[:4] + "-" + volid[4:]) in machine.succeed("blkid -o export /dev/vda1"), "볼륨 ID 가 유지되지 않았다"
              machine.succeed("sh /etc/esp-install 2>&1")
              machine.succeed("ls /boot/EFI/Linux/*.efi")
              # 상태(PCR)가 그대로라 예측이 옛 정책과 같다 → 보통의 make-policy 는 「skipping update」 로 ESP 에 아무 것도 쓰지 않는다
              out = machine.succeed("${pcrlock} lock-secureboot-policy 2>&1; ${pcrlock} lock-secureboot-authority 2>&1; ${pcrlock} make-policy 2>&1")
              assert "skipping update" in out, out
              machine.fail("ls /boot/loader/credentials/pcrlock.*.cred")
              pcr_refresh(force=True)      # --force 가 있어야 ESP 의 credential 이 다시 써진다
              machine.succeed("ls /boot/loader/credentials/pcrlock.*.cred")
              reboot()
              unlock_with_pin()
              machine.wait_for_unit("multi-user.target")
              machine.wait_until_succeeds("mount | grep -q 'cryptdata on /data'", timeout=60)

          with subtest("E2: ESP 에 정책 credential 만 없으면 TPM 으로 못 열지만, 복구 암호로 부팅한 뒤 정책만 다시 만들면 재등록 없이 복구된다"):
              machine.succeed("rm -f /boot/loader/credentials/pcrlock.*.cred; sync")
              reboot()
              unlock_with_pin()
              machine.wait_for_console_text("find pcrlock policy")
              machine.wait_for_unit("multi-user.target")
              assert not data_mounted(), "credential 이 없는데 열렸다"
              pcr_refresh(force=True)      # PCR 은 변하지 않았으니 옛 정책을 만족한다 → NV 는 그대로, ESP 의 credential 만 다시 쓰임(--force)
              reboot()
              unlock_with_pin()
              machine.wait_for_unit("multi-user.target")
              machine.wait_until_succeeds("mount | grep -q 'cryptdata on /data'", timeout=60)
        ''
      }
    '';
}
