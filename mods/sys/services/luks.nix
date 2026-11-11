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
  };
  os = lib.mkIf cfg.enable {
    boot.initrd.systemd.enable = true;
    boot.initrd.luks.devices.${cfg.name} = {
      inherit (cfg) device allowDiscards crypttabExtraOpts;
    };
  };
})
