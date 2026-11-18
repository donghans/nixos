{mkMod, ...}:
# Secure Boot(lanzaboote) 골격 (plan boot-security S3c; 켜는 것은 S5). 기본은 꺼짐 — 켜지 않으면 아무 것도 바꾸지 않는다.
#  - lanzaboote 모듈은 `core/lib/host.nix` 가 모든 호스트에 넣는다(`boot.lanzaboote.enable` 이 꺼져 있으면 효과 없음).
#  - 켜면 `systemd-boot` 를 끄고(`boot.loader.systemd-boot.enable = false`) lanzaboote 가 서명한 UKI 를 ESP 에 둔다. 서명 키는 `sbctl` 로 `pkiBundle` 에 만든다.
#  - **rEFInd mod 와 함께 쓰려면**: lanzaboote 는 `systemd-boot` 설치 경로 대신 `boot.loader.external.installHook` 을 써서 refind mod 의 `extraInstallCommands` 가 **돌지 않는다**
#    (그래서 refind mod 가 `boot.lanzaboote.package` 를 `lzbt` 래퍼로 바꿔 lzbt 뒤에 rEFInd 복사와 sbsign 을 한다 — mods/sys/services/refind.nix).
#  - 서명 키 백업 위치(plan D10)가 정해지기 전에는 켜지 않는다.
#  - 켜면 점검·복구 보조 명령 `secureboot-doctor` 가 함께 설치된다(상태·검증·ESP 백업·키 등록·빈 dbx 채우기). 운영 지침과 상황별 대응은 `hosts/msi-summit-me/SECURE-BOOT.md`.
mkMod __curPos "Secure Boot(lanzaboote) 골격: systemd-boot 를 끄고 서명된 UKI 를 둔다 (S5 에서 켬)" ({
  cfg,
  lib,
  pkgs,
  ...
}: let
  doctor = pkgs.writeShellApplication {
    name = "secureboot-doctor";
    runtimeInputs = [pkgs.sbctl pkgs.coreutils pkgs.util-linux pkgs.gnugrep pkgs.gawk pkgs.gnutar pkgs.python3 pkgs.p7zip pkgs.systemd];
    text = ''
      EFIVARS=/sys/firmware/efi/efivars
      G_GLOBAL=8be4df61-93ca-11d2-aa0d-00e098032b8c   # EFI_GLOBAL_VARIABLE (PK, KEK, SecureBoot, SetupMode, *Default)
      G_DB=d719b2cb-3d3a-4596-a3bc-dad00e67656f        # EFI_IMAGE_SECURITY_DATABASE (db, dbx)
      PKI=${cfg.pkiBundle}

      need_root() {
        if [ "$(id -u)" -ne 0 ]; then exec sudo "$0" "$@"; fi
      }

      var_size() { # 이름 GUID -> 본문 바이트 수(속성 4바이트 제외) 또는 "없음"
        if [ -e "$EFIVARS/$1-$2" ]; then echo $(( $(stat -c %s "$EFIVARS/$1-$2") - 4 )); else echo "없음"; fi
      }
      var_byte() { # 이름 GUID -> 첫 바이트 값
        od -An -tu1 -j4 -N1 "$EFIVARS/$1-$2" 2>/dev/null | tr -d ' ' || true
      }
      is_factory() { # PK|KEK 이름 -> 0: 공장 기본값과 같음
        [ -e "$EFIVARS/$1-$G_GLOBAL" ] && [ -e "$EFIVARS/$1Default-$G_GLOBAL" ] \
          && cmp -s <(tail -c +5 "$EFIVARS/$1-$G_GLOBAL") <(tail -c +5 "$EFIVARS/$1Default-$G_GLOBAL")
      }

      cmd_status() {
        need_root status
        echo "== Secure Boot 상태 =="
        sb=$(var_byte SecureBoot "$G_GLOBAL"); sm=$(var_byte SetupMode "$G_GLOBAL")
        sb_txt=꺼짐; if [ "$sb" = 1 ]; then sb_txt=켜짐; fi
        sm_txt='꺼짐(User Mode)'; if [ "$sm" = 1 ]; then sm_txt='켜짐(키 등록 가능)'; fi
        echo "SecureBoot: $sb_txt   SetupMode: $sm_txt"
        echo
        echo "== 펌웨어 키 데이터베이스(본문 바이트) =="
        for v in PK KEK; do
          note=""
          if [ -e "$EFIVARS/$v-$G_GLOBAL" ]; then
            if is_factory "$v"; then note='공장 기본값과 같음(우리 키 아님)'; else note='공장 기본값과 다름(사용자 키 포함)'; fi
          fi
          printf '%-4s %8s  %s\n' "$v" "$(var_size "$v" "$G_GLOBAL")" "$note"
        done
        printf '%-4s %8s\n' db "$(var_size db "$G_DB")"
        dbx_note=""
        if [ ! -e "$EFIVARS/dbx-$G_DB" ]; then dbx_note='← 없음: secureboot-doctor dbx-init <DBXUpdate.bin|.cab> 로 채운다'; fi
        printf '%-4s %8s  %s\n' dbx "$(var_size dbx "$G_DB")" "$dbx_note"
        echo
        echo "== 서명 키(디스크) =="
        for k in PK KEK db; do
          if [ -e "$PKI/keys/$k/$k.key" ]; then echo "$k: 있음"; else echo "$k: 없음 ($PKI/keys/$k/$k.key)"; fi
        done
        echo
        echo "== ESP 서명 검증(sbctl verify) =="
        out=$(sbctl verify 2>&1 || true)
        echo "서명됨: $(echo "$out" | grep -c '✓')개, 서명 안 됨: $(echo "$out" | grep -c '✗')개"
        echo "$out" | grep '✗' | sed 's/^/  /' || true
        echo "  (EFI/nixos/kernel-*.efi 는 lanzaboote 가 서명 UKI 에 박은 해시로 검증하므로 서명 안 됨으로 나와도 정상)"
        echo
        echo "== 백업 =="
        newest=$(find /home -maxdepth 2 -name 'esp-backup-*.tar' -printf '%T@ %p\n' 2>/dev/null | sort -nr | head -1 | cut -d' ' -f2- || true)
        if [ -n "$newest" ]; then
          echo "ESP 백업: $newest ($(( ( $(date +%s) - $(stat -c %Y "$newest") ) / 86400 ))일 전)"
        else
          echo "ESP 백업: 없음 — secureboot-doctor backup-esp"
        fi
        echo
        echo "== dbx 갱신(fwupd) =="
        if [ -f /var/lib/fwupd-check/last-result ]; then
          echo "마지막 확인: $(date -d @"$(stat -c %Y /var/lib/fwupd-check/last-result)" '+%F %T')"
          grep -E 'New version' /var/lib/fwupd-check/last-result | sed 's/^/  갱신 있음: /' || echo "  갱신 없음(마지막 확인 기준)"
        else
          echo "fwupd 확인 기록 없음(fwupd 모듈이 꺼져 있거나 아직 안 돌았음)"
        fi
      }

      cmd_verify() {
        need_root verify
        sbctl verify || true
        echo "(EFI/nixos/kernel-*.efi 의 '서명 안 됨'은 정상: 서명 UKI 의 해시로 검증)"
      }

      cmd_backup_esp() {
        need_root backup-esp "$@"
        home=$(getent passwd "''${SUDO_USER:-$USER}" | cut -d: -f6)
        dest=''${1:-$home/esp-backup-$(date +%Y%m%d).tar}
        tar -C /boot -cf "$dest" .
        chown "''${SUDO_USER:-root}" "$dest"; chmod 600 "$dest"
        echo "ESP 백업: $dest ($(du -h "$dest" | cut -f1), $(tar -tf "$dest" | wc -l)개 항목)"
        echo "복구용 USB 에도 복사해 둘 것."
      }

      cmd_enroll() {
        need_root enroll
        if [ "$(var_byte SetupMode "$G_GLOBAL")" != 1 ]; then
          echo "Setup Mode 가 아니다. BIOS 에서: Factory Default Key Provisioning=Disabled → Reset To Setup Mode → 저장 후 부팅. (SECURE-BOOT.md 참고)" >&2
          exit 1
        fi
        sbctl enroll-keys --microsoft --firmware-builtin
        echo "등록 완료. BIOS 에서 Secure Boot Support 를 Enabled 로 바꾸고, dbx 가 없으면 secureboot-doctor dbx-init 을 한다."
      }

      cmd_dbx_init() {
        need_root dbx-init "$@"
        src=''${1:-}
        if [ -z "$src" ]; then echo "사용법: secureboot-doctor dbx-init <DBXUpdate*.bin|*.cab>" >&2; exit 1; fi
        if [ -e "$EFIVARS/dbx-$G_DB" ]; then
          echo "dbx 가 이미 있다. 갱신은 fwupdmgr(refresh → get-updates → update)로 한다." >&2
          exit 1
        fi
        tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
        case "$src" in
          *.cab) 7z x -y "$src" -o"$tmp" >/dev/null; bin=$(find "$tmp" -name '*.bin' | head -1) ;;
          *) bin=$src ;;
        esac
        [ -f "''${bin:-}" ] || { echo "dbx 파일(.bin)을 찾지 못함" >&2; exit 1; }
        echo "적용할 파일: $bin ($(stat -c %s "$bin")바이트, sha256 $(sha256sum "$bin" | cut -c1-16)…)"
        echo "펌웨어가 KEK 서명을 검증한다(위조 파일은 거부됨). 되돌리려면 Setup Mode 가 필요하다."
        read -r -p "진행할까요? [y/N] " yn
        [ "$yn" = y ] || { echo "취소"; exit 1; }
        python3 - "$bin" "$EFIVARS/dbx-$G_DB" <<'PY'
      import os, struct, sys
      data = open(sys.argv[1], 'rb').read()
      attr = 0x01 | 0x02 | 0x04 | 0x20 | 0x40  # NV|BS|RT|TIME_BASED_AUTH|APPEND_WRITE
      fd = os.open(sys.argv[2], os.O_WRONLY | os.O_CREAT, 0o644)
      try:
          n = os.write(fd, struct.pack('<I', attr) + data)
          print('쓴 바이트', n)
      finally:
          os.close(fd)
      PY
        echo "dbx 크기: $(var_size dbx "$G_DB")바이트. 이후 갱신은 fwupdmgr 로."
      }

      cmd_help() {
        cat <<'EOF2'
      secureboot-doctor — Secure Boot 점검·복구 보조 (필요하면 sudo 로 다시 실행한다)
        status        상태 요약: SB·SetupMode, PK/KEK/db/dbx, 서명 키, ESP 서명, 백업, dbx 갱신
        verify        sbctl verify (ESP 의 EFI 파일 서명 확인)
        backup-esp [경로]   ESP(/boot) 전체를 tar 로 백업(기본 ~/esp-backup-YYYYMMDD.tar)
        enroll        Setup Mode 에서 키 등록(sbctl enroll-keys --microsoft --firmware-builtin)
        dbx-init <파일>     dbx 가 없을 때 DBXUpdate .bin/.cab 를 처음 한 번 채운다
      상황별 대응: hosts/msi-summit-me/SECURE-BOOT.md
      빠른 복구: 부팅이 안 되면 BIOS(Del/F2)에서 Secure Boot Support 를 Disabled 로 → 부팅 → secureboot-doctor status
      EOF2
      }

      case "''${1:-help}" in
        status) cmd_status ;;
        verify) cmd_verify ;;
        backup-esp) shift; cmd_backup_esp "$@" ;;
        enroll) cmd_enroll ;;
        dbx-init) shift; cmd_dbx_init "$@" ;;
        help|-h|--help) cmd_help ;;
        *) echo "알 수 없는 명령: $1" >&2; cmd_help; exit 1 ;;
      esac
    '';
  };
in {
  options = {
    pkiBundle = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/sbctl";
      description = "Directory holding the Secure Boot signing keys (created by `sbctl create-keys`). Back it up before enabling (plan D10).";
    };
  };
  os = lib.mkIf cfg.enable {
    boot.loader.systemd-boot.enable = lib.mkForce false;
    boot.lanzaboote = {
      enable = true;
      inherit (cfg) pkiBundle;
    };
    environment.systemPackages = [pkgs.sbctl doctor];
  };
})
