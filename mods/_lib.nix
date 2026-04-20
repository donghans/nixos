{lib}: let
  # mods/ 루트 절대 경로 — pathFromPos에서 상대 경로 계산에 사용
  modsRoot = toString ./.;

  # __curPos 위치에서 option path 자동 유도
  # 예: { file = ".../mods/sys/services/docker.nix"; ... } → "mods.sys.services.docker"
  pathFromPos = pos: let
    relative = lib.removePrefix (modsRoot + "/") pos.file;
    withoutNix = lib.removeSuffix ".nix" relative;
  in
    "mods." + lib.replaceStrings ["/"] ["."] withoutNix;

  # mkNamedMod — 경로 문자열을 명시적으로 지정하는 저수준 헬퍼
  # 일반적으로는 mkMod(__curPos 자동 경로)를 사용할 것.
  # default.nix 처럼 __curPos 경로가 올바르지 않은 경우에만 사용.
  #
  # 인자:
  #   path    — 옵션 경로 문자열 (예: "mods.gui.apps.vivaldi")
  #   desc    — mkEnableOption 설명. null이면 enable 옵션을 추가하지 않음.
  #   bodyFn  — { cfg, config, lib, pkgs, unstable, ... } 를 받아
  #              { options?, os?, hm? } 를 반환하는 함수
  #
  # 동작:
  #   - cfg         : path 기반으로 config에서 자동 해결 (desc=null이면 null)
  #   - enable      : desc가 null이 아니면 자동 추가 (mkEnableOption desc)
  #   - os/hm       : 값이 plain attrset이면 mkIf cfg.enable 자동 적용
  #                   _type 필드가 있는 값(mkMerge, mkIf, mkOverride 등)은 그대로 통과
  #   - isNixOS 분기는 내부에서 처리 (모듈 시그니처에 선언 불필요)
  #   - _module.args 항목(예: hyprTerm)은 bodyFn의 named arg로 받으면 안 됨:
  #     innerModule이 {imports=[]} 래퍼 안에 있어 _module.args 키가 args 키셋에 없음.
  #     대신 bodyFn 안에서 config._module.args.hyprTerm 으로 lazily 접근할 것.
  #   - sub-module imports가 필요하면 외부 모듈에서 직접 선언:
  #     { imports = (mkMod __curPos ...).imports ++ [./sub1.nix ...]; }
  #
  # 사용 예:
  #   mkMod __curPos "Vivaldi browser" ({ cfg, pkgs, ... }: {
  #     options = { package = lib.mkPackageOption pkgs "vivaldi" {}; };
  #     os = { environment.systemPackages = [ cfg.package ]; };
  #     hm = { home.packages = [ cfg.package ]; };
  #   })
  #
  #   # mkMerge가 필요한 경우 — _type 감지로 자동 통과
  #   mkMod __curPos "Foo" ({ cfg, config, lib, ... }: {
  #     os = lib.mkMerge [
  #       (lib.mkIf cfg.enable { services.foo.enable = true; })
  #       (lib.mkIf (cfg.enable && config.services.bar.enable) { ... })
  #     ];
  #   })
  #
  #   # enable 없는 항상-켜지는 모듈 (desc=null)
  #   mkMod __curPos null ({ pkgs, ... }: {
  #     hm = { programs.fuzzel = { enable = true; }; };
  #   })
  #
  mkNamedMod = path: desc: bodyFn: let
    innerModule = {
      config,
      lib,
      pkgs,
      isNixOS ? false,
      ...
    } @ args: let
      pathParts = lib.splitString "." path;
      cfg =
        if desc == null
        then null
        else lib.getAttrFromPath pathParts config;

      body = bodyFn (args // {inherit cfg;});

      # plain attrset → mkIf cfg.enable 자동 적용
      # _type 있음(mkIf/mkMerge/mkOverride 등) → 그대로 통과
      # desc = null(enable 없음) → 그대로 통과
      autoWrap = v:
        if desc == null
        then v
        else if v ? _type
        then v
        else lib.mkIf cfg.enable v;

      baseOptions = lib.setAttrByPath pathParts (
        lib.optionalAttrs (desc != null) {enable = lib.mkEnableOption desc;}
        // (body.options or {})
      );
    in {
      options = baseOptions;
      # osImports/hmImports는 innerModule.imports에서 지원하지 않음:
      # imports는 모듈 수집 단계(collection phase)에서 평가되는데,
      # 이 시점에는 _module.args(예: hyprTerm) 가 아직 해결되지 않아
      # bodyFn 호출 시 "called without required argument" 오류가 발생함.
      # sub-module imports가 필요하면 외부 모듈에서 직접 imports = [...] 사용.
      config =
        if isNixOS
        then autoWrap (body.os or {})
        else autoWrap (body.hm or {});
    };
  in {imports = [innerModule];};

  # mkMod — __curPos에서 파일 위치를 자동 유도하는 기본 헬퍼 (구 mkModHere)
  #
  # 사용 예:
  #   { mkMod, ... }:
  #   mkMod __curPos "Docker Daemon and tools" ({ cfg, config, ... }: {
  #     os = { virtualisation.docker.enable = true; };
  #   })
  #
  # __curPos는 호출 파일 안에서 평가되므로 해당 파일의 경로를 자동으로 가져온다.
  mkMod = pos: desc: bodyFn: mkNamedMod (pathFromPos pos) desc bodyFn;
in {
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

  inherit mkMod mkNamedMod;
}
