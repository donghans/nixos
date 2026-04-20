{lib}: let
  # mods/ 루트 절대 경로 — pathFromPos에서 상대 경로 계산에 사용
  modsRoot = toString ../../mods;

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
  #   desc    — mkEnableOption 설명.
  #   bodyFn  — { cfg, config, lib, pkgs, unstable, ... } 를 받아
  #              { options?, os?, hm? } 를 반환하는 함수
  #
  # 동작:
  #   - cfg         : path 기반으로 config에서 자동 해결
  #   - enable      : 자동 추가 (mkEnableOption desc)
  #   - os/hm       : 값이 plain attrset이면 mkIf cfg.enable 자동 적용
  #                   _type 필드가 있는 값(mkMerge, mkIf, mkOverride 등)은 그대로 통과
  #   - forOS 분기는 내부에서 처리 (모듈 시그니처에 선언 불필요)
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
  mkNamedMod = path: desc: bodyFn: let
    innerModule = {
      config,
      lib,
      pkgs,
      forOS ? false,
      ...
    } @ args: let
      pathParts = lib.splitString "." path;
      cfg = lib.getAttrFromPath pathParts config;

      body = bodyFn (args // {inherit cfg pkgs;});

      # plain attrset → mkIf cfg.enable 자동 적용
      # _type 있음(mkIf/mkMerge/mkOverride 등) → 그대로 통과
      autoWrap = v:
        if v ? _type
        then v
        else lib.mkIf cfg.enable v;

      baseOptions = lib.setAttrByPath pathParts (
        {enable = lib.mkEnableOption desc;}
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
        if forOS
        then autoWrap (body.os or {})
        else autoWrap (body.hm or {});
    };
  in {imports = [innerModule];};

  # mkPartOf — 부모 모드의 enable에 종속되는 서브모듈 헬퍼
  #
  # 자체 enable 옵션을 선언하지 않고, 지정한 부모 경로의 cfg.enable에 따라 활성화됨.
  # TOML 프리셋에 개별 항목으로 노출되지 않는 서브모듈에 사용.
  #
  # 인자:
  #   parentPath — 부모 옵션 경로 문자열 (예: "mods.gui", "mods.sys.base")
  #   bodyFn     — { cfg, config, lib, pkgs, ... } 를 받아 { os?, hm? } 를 반환하는 함수
  #                cfg = 부모의 config.mods.* attrset
  #
  # 사용 예:
  #   { mkPartOf, ... }:
  #   mkPartOf "mods.gui" ({ cfg, pkgs, lib, ... }: {
  #     os = { services.greetd.enable = true; };   # mkIf cfg.enable 자동 적용
  #     hm = { programs.fuzzel.enable = true; };   # mkIf cfg.enable 자동 적용
  #   })
  #
  mkPartOf = parentPath: bodyFn: let
    innerModule = {
      config,
      lib,
      pkgs,
      forOS ? false,
      ...
    } @ args: let
      parentParts = lib.splitString "." parentPath;
      cfg = lib.getAttrFromPath parentParts config;
      body = bodyFn (args // {inherit cfg pkgs;});
      autoWrap = v:
        if v ? _type
        then v
        else lib.mkIf cfg.enable v;
    in {
      config =
        if forOS
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

  # mkModOf — 부모 도메인 마스터 스위치에 자동 연결되는 서브모듈
  #
  # mkMod와 동일하지만 parentPath.enable = true 시 자동으로 enable = mkDefault true 설정.
  # 부모 파일(gui.nix, devel.nix 등)에서 연쇄 활성화를 명시할 필요 없이, 각 모듈 파일에서
  # 소속 도메인만 선언하면 마스터 스위치와 자동 연결된다.
  #
  # 사용 예:
  #   { mkModOf, ... }:
  #   mkModOf "mods.devel" __curPos "Node.js toolchain" ({ cfg, pkgs, ... }: {
  #     hm = { home.packages = [ pkgs.nodejs ]; };
  #   })
  #
  mkModOf = parentPath: pos: desc: bodyFn: let
    modulePath = pathFromPos pos;
    baseMod = mkNamedMod modulePath desc bodyFn;
    cascadeModule = {
      config,
      lib,
      ...
    }: let
      parentParts = lib.splitString "." parentPath;
      parentCfg = lib.getAttrFromPath parentParts config;
      moduleParts = lib.splitString "." modulePath;
    in {
      config =
        lib.mkIf parentCfg.enable
        (lib.setAttrByPath moduleParts {enable = lib.mkDefault true;});
    };
  in {
    imports = baseMod.imports ++ [cascadeModule];
  };

  # mkHostConfiguration — 호스트 파일 전용 통합 헬퍼
  # os/hm 블록을 한 파일에 선언하고, 빌더가 컨텍스트(forOS)에 따라 분기해 적용.
  # enable 옵션 없음 (호스트 파일은 항상 활성화).
  #
  # 사용 예:
  #   {mkHostConfiguration, ...}:
  #   mkHostConfiguration ({pkgs, lib, ...}: {
  #     os = { boot.kernelParams = ["amd_pstate=active"]; };
  #     hm = { services.hypridle.settings.listener = [...]; };
  #   })
  mkHostConfiguration = bodyFn: let
    innerModule = {
      forOS ? false,
      pkgs,
      ...
    } @ args: let
      body = bodyFn (args // {inherit pkgs;});
      selected =
        if forOS
        then (body.os or {})
        else (body.hm or {});
      # os/hm 블록 안의 imports를 최상위 module imports로 승격
      # (NixOS·HM 모듈 시스템 모두 {imports=[...]; config={...};} 구조를 동일하게 처리함)
      blockImports = selected.imports or [];
      configAttrs = builtins.removeAttrs selected ["imports"];
    in {
      imports = blockImports;
      config = configAttrs;
    };
  in {imports = [innerModule];};

  # 제외 규칙 (importDir / recursiveImportDir 공통)
  # _ prefix: 라이브러리·프라이빗 파일, .home.nix / .overlay.nix suffix: 조건부 로드 파일
  # default.nix: 오케스트레이터 (모듈 아님)
  isImportable = n:
    lib.hasSuffix ".nix" n
    && !lib.hasPrefix "_" n
    && !lib.hasSuffix ".home.nix" n
    && !lib.hasSuffix ".overlay.nix" n
    && n != "default.nix";

  # 디렉터리 내 NixOS 모듈 파일 목록 반환 (비재귀)
  importDir = dir: let
    contents = builtins.readDir dir;
    files =
      builtins.filter isImportable
      (builtins.attrNames (lib.filterAttrs (_: v: v == "regular") contents));
  in
    map (n: dir + "/${n}") files;

  # 디렉터리 트리 전체의 NixOS 모듈 파일 목록 반환 (재귀)
  # _ prefix 디렉터리도 skip (예: _preset/)
  recursiveImportDir = dir: let
    contents = builtins.readDir dir;
    files =
      builtins.filter isImportable
      (builtins.attrNames (lib.filterAttrs (_: v: v == "regular") contents));
    subdirs =
      builtins.attrNames
      (lib.filterAttrs (n: v: v == "directory" && !lib.hasPrefix "_" n) contents);
  in
    map (n: dir + "/${n}") files
    ++ builtins.concatLists (map (d: recursiveImportDir (dir + "/${d}")) subdirs);
in {
  # specialArgs로 주입할 모듈-facing 헬퍼 번들
  modArgs = {inherit mkMod mkNamedMod mkPartOf mkModOf mkHostConfiguration;};
  # 빌드 인프라 전용 (specialArgs에 안 감)
  inherit importDir recursiveImportDir;
}
