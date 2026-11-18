{mkMod, ...}:
# fwupd(펌웨어·Secure Boot 키 데이터베이스 갱신 데몬) — 노트북에서 Secure Boot 를 켠 뒤 `dbx`(금지 목록) 등을 `fwupdmgr` 로 받기 위해 켠다 (plan s5-secure-boot-exec §6, 2026-11-18).
#  - 배경: BIOS 「Reset To Setup Mode」가 `dbx` 까지 지우고 `sbctl enroll-keys` 는 `dbx` 를 복원하지 않는다. 처음에는 Microsoft `DBXUpdate.bin` 을 efivarfs 에 직접 append 했다.
#    이후 갱신은 fwupd(LVFS) 로 받는다: `fwupdmgr refresh && fwupdmgr get-updates && fwupdmgr update`. nixpkgs 모듈은 메타데이터 갱신 타이머만 있고 설치는 사람이 한다.
#  - lanzaboote 가 켜져 있으면 lanzaboote 모듈이 서명된 fwupd EFI 바이너리를 쓰게 해 준다(자동).
#  - 데몬은 D-Bus 활성화 방식이라 평소 상주하지 않는다(전력 영향은 측정하지 않았다).
mkMod __curPos "fwupd (LVFS 펌웨어·dbx 갱신 도구)" ({
  cfg,
  lib,
  ...
}: {
  options = {};
  os = lib.mkIf cfg.enable {
    services.fwupd.enable = true;
  };
})
