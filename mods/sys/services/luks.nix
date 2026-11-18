{mkMod, ...}:
# LUKS2 루트 골격 (plan boot-security S3c; 켜는 것은 S4 재설치 때). 기본은 꺼짐.
#  - systemd initrd 로 연다(kernel-lockdown mod 가 이미 켠다). 잠금 해제 방식(FIDO2·TPM·패스프레이즈)은 `crypttabExtraOpts` 로 정한다(plan D4).
#  - `device` 는 S4 에서 실제 파티션으로 채울 **자리표시값**이다. 켜기 전에 반드시 바꾼다.
#  - 디스크 포맷·헤더 백업은 이 mod 가 하지 않는다(plan §6 S4 체크리스트: `luksHeaderBackup`).
mkMod __curPos "LUKS2 루트(systemd initrd) 골격 (S4 에서 켬)" ({
  cfg,
  lib,
  ...
}: {
  options = {
    name = lib.mkOption {
      type = lib.types.str;
      default = "cryptroot";
      description = "Mapper name of the LUKS device (/dev/mapper/<name>).";
    };
    device = lib.mkOption {
      type = lib.types.str;
      default = "/dev/disk/by-partlabel/cryptroot";
      description = "Placeholder — set to the real LUKS partition in S4 before enabling.";
    };
    allowDiscards = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = "Pass TRIM through the LUKS layer (SSD).";
    };
    crypttabExtraOpts = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [];
      description = "Extra crypttab options, e.g. [\"fido2-device=auto\"] or [\"tpm2-device=auto\"].";
    };
    fido2 = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        initrd 에서 FIDO2 보안 키(LUKS 헤더에 `systemd-cryptenroll --fido2-device=auto` 로 등록한 슬롯)로 푼다(crypttab `fido2-device=auto`).
        키가 없으면 `token-timeout`(기본 30초) 뒤 암호 입력으로 넘어간다 — 복구 암호 슬롯은 그대로 둔다. nixpkgs 에 같은 구성의 시험(systemd-initrd-luks-fido2)이 있다.
        주의: FIDO2 는 부팅 체인을 확인하지 않는다(가짜 initrd 도 PIN·터치를 받으면 해제용 값을 얻는다). 체인 보호는 Secure Boot + BIOS 암호가 맡는다(hosts/msi-summit-me/SECURE-BOOT.md §2-10).
      '';
    };
    deviceTimeoutSec = lib.mkOption {
      type = lib.types.ints.positive;
      default = 600;
      description = ''
        initrd 에서 장치(root by-label 등)를 기다리는 최대 시간(초). systemd 기본은 90초인데, 사람이 LUKS 암호를 치는 시간(오입력 재시도 포함)이
        이를 넘으면 `Timed out waiting for device` → emergency 화면(쉘 없이 "Press Enter to continue")으로 떨어진다(2026-11-18 실기: 암호창 3.5초 → 입력 완료 93.7초, 타임아웃 91.97초).
        0(무제한)은 쓰지 않는다 — 암호와 무관한 장애(헤더 손상·장치 없음)에서 아무 안내 없이 멈춘다.
      '';
    };
  };
  os = lib.mkIf cfg.enable {
    boot.initrd.systemd.enable = true;
    # 오입력해도 포기하지 않고 암호창을 계속 다시 띄운다(crypttab `tries=0`). 기본(3회)이면 3번 틀린 뒤 암호창이 사라지고 타임아웃 뒤 emergency 화면에서 Enter 를 눌러야 재시도된다(2026-11-18 VM 시험).
    boot.initrd.luks.devices.${cfg.name} = {
      inherit (cfg) device allowDiscards;
      crypttabExtraOpts = ["tries=0"] ++ lib.optional cfg.fido2 "fido2-device=auto" ++ cfg.crypttabExtraOpts;
    };
    boot.initrd.systemd.settings.Manager.DefaultDeviceTimeoutSec = cfg.deviceTimeoutSec;
  };
})
