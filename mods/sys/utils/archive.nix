{mkMod, ...}:
mkMod __curPos "Archive tools (7z)" ({pkgs, ...}: {
  # zip/unzip은 따로 안 둠 — Xarchiver가 zip도 7z로 처리하도록 설정되어 있고
  # (Preferences > Archive > "Prefer unzip for zip files" 끔, xarchiverrc의
  # prefer_unzip=false), 7z 자체 CLI(`7z a`/`7z x` 등)로 zip/7z 압축·해제가
  # 다 되므로 unzip 6.0의 local/central 필드 불일치 버그(경고성 exit 1 → GUI가
  # 실패로 오인)를 원천적으로 우회함. 자세한 경위는 mods/gui/utils/xarchiver.nix 참고.
  os.environment.systemPackages = with pkgs; [p7zip];
  hm.home.packages = with pkgs; [p7zip];
})
