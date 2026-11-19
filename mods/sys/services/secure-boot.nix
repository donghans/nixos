{mkMod, ...}:
# Secure Boot(lanzaboote) 골격 (plan boot-security S3c; 켜는 것은 S5). 기본은 꺼짐 — 켜지 않으면 아무 것도 바꾸지 않는다.
#  - lanzaboote 모듈은 `core/lib/host.nix` 가 모든 호스트에 넣는다(`boot.lanzaboote.enable` 이 꺼져 있으면 효과 없음).
#  - 켜면 `systemd-boot` 를 끄고(`boot.loader.systemd-boot.enable = false`) lanzaboote 가 서명한 UKI 를 ESP 에 둔다. 서명 키는 `sbctl` 로 `pkiBundle` 에 만든다.
#  - **rEFInd mod 와 함께 쓰려면**: lanzaboote 는 `systemd-boot` 설치 경로 대신 `boot.loader.external.installHook` 을 써서 refind mod 의 `extraInstallCommands` 가 **돌지 않는다**
#    (그래서 refind mod 가 `boot.lanzaboote.package` 를 `lzbt` 래퍼로 바꿔 lzbt 뒤에 rEFInd 복사와 sbsign 을 한다 — mods/sys/services/refind.nix).
#  - 서명 키 백업 위치(plan D10)가 정해지기 전에는 켜지 않는다.
#  - 켜면 점검·복구 보조 명령 `nixseal`(상태·검증·ESP 백업·키 등록·빈 dbx 채우기·LUKS 슬롯·헤더 백업)이 함께 설치된다. 운영 지침과 상황별 대응은 `hosts/msi-summit-me/SECURE-BOOT.md`.
mkMod __curPos "Secure Boot(lanzaboote) 골격: systemd-boot 를 끄고 서명된 UKI 를 둔다 (S5 에서 켬)" ({
  cfg,
  lib,
  pkgs,
  ...
}: let
  # 빈 dbx 를 처음 채울 때 쓰는 Microsoft DBXUpdate(KEK 서명된 공개 해시 목록, 비밀 없음). 커밋·해시 고정이라 한 번 받으면 store 에 남아 오프라인에서도 쓴다.
  # 출처 microsoft/secureboot_objects (BSD-2-Clause-Patent, Copyright Microsoft Corporation). 이후 갱신은 fwupd 가 한다.
  # 2026-11-19 확인: 이 파일의 서명 목록(21292바이트)은 msi-summit-me 에 이미 적용된 dbx 와 바이트 단위로 같다.
  dbxInit = pkgs.fetchurl {
    url = "https://raw.githubusercontent.com/microsoft/secureboot_objects/f75f97f6da5ca70ac23c7daf12cac069131601aa/PostSignedObjects/DBX/amd64/DBXUpdate.bin";
    hash = "sha256-IInjEl5hE3bLRDJrV2VnQlVEOySE+I3pclGTnRgFX2g=";
  };
  # 점검·복구 보조 명령 `nixseal`(plan/nixseal): 로직은 core/scripts/nixseal.py(ISO 와 공용 단일 파일)를 store 로 복사해 실행한다.
  # 이 래퍼가 PATH(runtimeInputs)와 nix 가 정하는 값(pkiBundle·내장 dbx)을 환경변수로 준다. NIXSEAL_SELF 는 root 가 아닐 때 sudo 로 다시 실행할 경로.
  nixseal = pkgs.writeShellApplication {
    name = "nixseal";
    runtimeInputs = [pkgs.sbctl pkgs.coreutils pkgs.util-linux pkgs.gnugrep pkgs.gawk pkgs.gnutar pkgs.python3 pkgs.systemd pkgs.cryptsetup pkgs.fwupd];
    text = ''
      export NIXSEAL_PKI=${cfg.pkiBundle}
      export NIXSEAL_DBX=${dbxInit}
      export NIXSEAL_PCRLOCK=${pkgs.systemd}/lib/systemd/systemd-pcrlock
      export NIXSEAL_SELF="$0"
      exec python3 -I ${../../../core/scripts/nixseal.py} "$@"
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
    environment.systemPackages = [pkgs.sbctl nixseal];
  };
})
