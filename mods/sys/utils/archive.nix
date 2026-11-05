{mkMod, ...}:
mkMod __curPos "Archive tools (7zz + unar)" ({pkgs, ...}: let
  # 공식 7-Zip 리눅스판(7zz, 원작자 유지). p7zip(2016 이후 비공식 포트)을 대체함.
  # 관례상/문서상 쓰는 `7z` 명령 이름은 7zz 로 연결해 둠(Xarchiver 는 7zz 를 먼저 찾음).
  sevenzip = pkgs.symlinkJoin {
    name = "7zz-with-7z-alias";
    paths = [pkgs._7zz];
    postBuild = ''
      ln -s ${pkgs._7zz}/bin/7zz $out/bin/7z
    '';
  };
  # unar/lsar: 한글 Windows(CP949)가 만든 zip 처럼 UTF-8 표시가 없는 파일명의 인코딩을 자동 감지함.
  # 7z 는 이걸 못 해서 이름이 깨짐 → Xarchiver 의 zip 목록·풀기·테스트는 unar 가 맡음
  # (mods/_data/xarchiver/zip-unar.patch, mods/gui/utils/xarchiver.nix 참고).
  tools = [sevenzip pkgs.unar];
in {
  # zip/unzip은 따로 안 둠 — Xarchiver가 zip도 7z로 처리하도록 설정되어 있고
  # (Preferences > Archive > "Prefer unzip for zip files" 끔, xarchiverrc의
  # prefer_unzip=false), 7z 자체 CLI(`7z a`/`7z x` 등)로 zip/7z 압축·해제가
  # 다 되므로 unzip 6.0의 local/central 필드 불일치 버그(경고성 exit 1 → GUI가
  # 실패로 오인)를 원천적으로 우회함. 자세한 경위는 mods/gui/utils/xarchiver.nix 참고.
  os.environment.systemPackages = tools;
  hm.home.packages = tools;
})
