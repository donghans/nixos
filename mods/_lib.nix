{ lib }:
{
  # 디렉터리 내 NixOS 모듈 파일 목록 반환
  # 제외: _ prefix (라이브러리/프라이빗), .home.nix suffix (조건부 로드 파일)
  importDir = dir:
    let
      contents = builtins.readDir dir;
      isImportable = n:
        lib.hasSuffix ".nix" n
        && !lib.hasPrefix "_" n
        && !lib.hasSuffix ".home.nix" n;
      files = builtins.filter isImportable
        (builtins.attrNames (lib.filterAttrs (_: v: v == "regular") contents));
    in map (n: dir + "/${n}") files;
}
