{mkMod, ...}:
# Secure Boot(lanzaboote) 골격 (plan boot-security S3c; 켜는 것은 S5). 기본은 꺼짐 — 켜지 않으면 아무 것도 바꾸지 않는다.
#  - lanzaboote 모듈은 `core/lib/host.nix` 가 모든 호스트에 넣는다(`boot.lanzaboote.enable` 이 꺼져 있으면 효과 없음).
#  - 켜면 `systemd-boot` 를 끄고(`boot.loader.systemd-boot.enable = false`) lanzaboote 가 서명한 UKI 를 ESP 에 둔다. 서명 키는 `sbctl` 로 `pkiBundle` 에 만든다.
#  - **rEFInd mod 와 함께 쓰려면**: lanzaboote 는 `systemd-boot` 설치 경로 대신 `boot.loader.external.installHook` 을 써서 refind mod 의 `extraInstallCommands` 가 **돌지 않는다**
#    (그래서 refind mod 에 assertion 이 있다). S5 에서 hook 을 감싸 rEFInd 복사와 `sbctl sign` 을 추가해야 한다.
#  - 서명 키 백업 위치(plan D10)가 정해지기 전에는 켜지 않는다.
mkMod __curPos "Secure Boot(lanzaboote) 골격: systemd-boot 를 끄고 서명된 UKI 를 둔다 (S5 에서 켬)" ({
  cfg,
  lib,
  ...
}: {
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
  };
})
