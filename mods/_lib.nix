{lib}: {
  # 디렉터리 내 NixOS 모듈 파일 목록 반환
  # 제외: _ prefix (라이브러리/프라이빗), .home.nix suffix (조건부 로드 파일)
  importDir = dir: let
    contents = builtins.readDir dir;
    isImportable = n:
      lib.hasSuffix ".nix" n
      && !lib.hasPrefix "_" n
      && !lib.hasSuffix ".home.nix" n
      && !lib.hasSuffix ".overlay.nix" n;
    files =
      builtins.filter isImportable
      (builtins.attrNames (lib.filterAttrs (_: v: v == "regular") contents));
  in
    map (n: dir + "/${n}") files;

  # mkMod — NixOS + Home Manager 이중 컨텍스트 모듈 선언 헬퍼
  #
  # 인자:
  #   path    — 옵션 경로 문자열 (예: "mods.gui.apps.vivaldi")
  #   desc    — mkEnableOption 설명. null이면 enable 옵션을 추가하지 않음.
  #   bodyFn  — { cfg, config, lib, pkgs, unstable, ... } 를 받아
  #              { options?, os?, hm? } 를 반환하는 함수
  #
  # 동작:
  #   - cfg    : path 기반으로 config에서 자동 해결
  #   - enable : desc가 null이 아니면 자동 추가 (mkEnableOption desc)
  #   - os/hm  : 값이 plain attrset이면 mkIf cfg.enable 자동 적용
  #              _type 필드가 있는 값(mkMerge, mkIf, mkOverride 등)은 그대로 통과
  #   - isNixOS 분기는 내부에서 처리 (모듈 시그니처에 선언 불필요)
  #
  # 사용 예:
  #   mkMod "mods.gui.apps.vivaldi" "Vivaldi browser" ({ cfg, pkgs, ... }: {
  #     options = { package = lib.mkPackageOption pkgs "vivaldi" {}; };
  #     os = { environment.systemPackages = [ cfg.package ]; };
  #     hm = { home.packages = [ cfg.package ]; };
  #   })
  #
  #   # mkMerge가 필요한 경우 — _type 감지로 자동 통과
  #   mkMod "mods.sys.services.foo" "Foo" ({ cfg, config, lib, ... }: {
  #     os = lib.mkMerge [
  #       (lib.mkIf cfg.enable { services.foo.enable = true; })
  #       (lib.mkIf (cfg.enable && config.services.bar.enable) { ... })
  #     ];
  #   })
  #
  #   # enable 없는 항상-켜지는 모듈
  #   mkMod "mods.gui.core.fuzzel" null ({ pkgs, ... }: {
  #     hm = { programs.fuzzel = { enable = true; }; };
  #   })
  mkMod = path: desc: bodyFn:
    {config, lib, pkgs, isNixOS ? false, ...}@args: let
      pathParts = lib.splitString "." path;
      cfg = lib.getAttrFromPath pathParts config;

      body = bodyFn (args // {inherit cfg;});

      # plain attrset → mkIf cfg.enable 자동 적용
      # _type 있음(mkIf/mkMerge/mkOverride 등) → 그대로 통과
      # desc = null(enable 없음) → 그대로 통과
      autoWrap = v:
        if desc == null then v
        else if v ? _type then v
        else lib.mkIf cfg.enable v;

      baseOptions = lib.setAttrByPath pathParts (
        lib.optionalAttrs (desc != null) {enable = lib.mkEnableOption desc;}
        // (body.options or {})
      );
    in {
      options = baseOptions;
      config =
        if isNixOS
        then autoWrap (body.os or {})
        else autoWrap (body.hm or {});
    };
}
