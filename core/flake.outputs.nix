{
  nixpkgs,
  home-manager,
  ...
} @ inputs: let
  # == Overlays ==
  # *.overlay.nix 파일을 mods/ 하위에서 자동 탐색하여 customOverlays에 추가
  overlayFiles =
    builtins.filter
    (f: nixpkgs.lib.hasSuffix ".overlay.nix" (toString f))
    (nixpkgs.lib.filesystem.listFilesRecursive ../mods);
  customOverlays =
    [
      (import ./lib/mk-wrapper.nix)
    ]
    ++ map import overlayFiles;

  # == toConfig: resolved.mods JSON → Nix module attrs ==
  toConfig = val:
    if builtins.isBool val
    then {enable = val;}
    else if builtins.isAttrs val
    then
      nixpkgs.lib.mapAttrs (
        k: v:
          if k == "enable" && builtins.isBool v
          then v
          else toConfig v
      )
      val
    else {};

  # == resolved.json 로드 ==
  # (목적: AI 및 직접 nix 실행 방지용 명시적 에러)
  allResolved =
    if !(builtins.pathExists ../resolved.json)
    then
      throw ''
        ============================================================
        ERROR: resolved.json not found.

        This flake CANNOT be evaluated directly with nix commands.
        It requires nhw to prepare an isolated build environment
        and generate resolved.json before nix is invoked.

        DO NOT run these directly — they will always fail:
          nix build .#<hostname>
          nix flake check
          nixos-rebuild switch --flake .#<hostname>
          home-manager switch --flake .#<user>@<hostname>

        Use nhw instead:
          nhw home switch          # apply home-manager config
          nhw os switch            # apply NixOS system config
          nhw check                # run full integrity checks

        WHY: nhw copies sources to .build/, resolves
        host metadata into resolved.json, then invokes nix from
        that isolated directory. Skipping nhw breaks this step.
        ============================================================
      ''
    else builtins.fromJSON (builtins.readFile ../resolved.json);

  # == presets.json 로드 ==
  allPresets =
    if !(builtins.pathExists ../presets.json)
    then throw "ERROR: presets.json not found. Run nhw to generate it."
    else builtins.fromJSON (builtins.readFile ../presets.json);

  # == 호스트명 자동탐색: resolved.json 키 목록 ==
  hostNames = builtins.attrNames allResolved;

  # == 공통 workspaceMeta (base.toml 데이터는 모든 호스트 동일) ==
  anyResolved = allResolved.${builtins.head hostNames};
  workspaceMeta = {
    inherit (anyResolved) username git rollingStateVersion;
    inherit (anyResolved) timeZone defaultLocale extraLocale;
    inherit (anyResolved) diskDevice bootDevice;
    gitName = anyResolved.git.name;
    gitEmail = anyResolved.git.email;
    inherit (anyResolved.git) nixosRepo;
  };

  # == Builders ==
  builders = import ./lib/builders.nix {
    inherit inputs customOverlays;
  };
  inherit (builders) mkHost mkHostContext;

  # == ISO 빌더 헬퍼 (system만 다르고 나머지 동일) ==
  mkISO = system:
    mkHost {
      hostname = "nixos-iso";
      inherit system;
      type = "desktop";
      isISO = true;
      # ISO는 ephemeral 환경이므로 resolver 없이 base.toml의 rollingStateVersion으로 고정
      workspaceMeta = workspaceMeta // {stateVersion = workspaceMeta.rollingStateVersion;};
      # ISO는 resolver를 거치지 않으므로 iso 프리셋을 직접 주입
      extraModules = [
        {mods = toConfig allPresets.iso.mods;}
        ({
          options,
          lib,
          ...
        }:
          import ./lib/mk-preset.nix {
            inherit lib options;
            presetName = "iso";
            presetsJsonPath = ../presets.json;
          })
      ];
    };

  # == Per-host 공통 바인딩 헬퍼 (nixosConfigurations + homeConfigurations 공유) ==
  mkPerHostBindings = name: let
    resolved = allResolved.${name};
    perHostMeta =
      workspaceMeta
      // {
        inherit (resolved) hostname type;
        inherit (resolved) stateVersion;
        ramGb = resolved.ramGb       or null;
        swapGb = resolved.swapGb      or null;
        tmpfsSize = resolved.tmpfsSize   or null;
        zramPercent = resolved.zramPercent or null;
      };
    presetMods = allPresets.${resolved.preset}.mods;
    mergedMods = nixpkgs.lib.recursiveUpdate presetMods resolved.mods;
    modsModule = {mods = toConfig mergedMods;};
    # root는 sys 모듈만 사용. 새 사용자 전용 카테고리 추가 시 여기에 반영
    rootExcludedMods = ["gui" "devel"];
    rootModsModule = {mods = toConfig (builtins.removeAttrs mergedMods rootExcludedMods);};
    coverageModule = {
      options,
      lib,
      ...
    }:
      import ./lib/mk-preset.nix {
        inherit lib options;
        presetName = resolved.preset;
        presetsJsonPath = ../presets.json;
      };
  in {inherit resolved perHostMeta modsModule rootModsModule coverageModule;};
in {
  # == Output: NixOS Configurations ==
  nixosConfigurations =
    (nixpkgs.lib.genAttrs hostNames (name: let
      h = mkPerHostBindings name;
      inherit (h) resolved perHostMeta modsModule coverageModule;
    in
      mkHost (resolved
        // {
          workspaceMeta = perHostMeta;
          extraModules = [modsModule coverageModule];
        })))
    // {
      # ISO는 resolved.json 없이 직접 호출 (host.toml 없는 특수 케이스)
      custom-iso = mkISO "x86_64-linux";
      custom-iso-aarch64 = mkISO "aarch64-linux";
    };

  # == Output: Home Configurations ==
  homeConfigurations = builtins.listToAttrs (nixpkgs.lib.concatMap (name: let
      h = mkPerHostBindings name;
      inherit (h) resolved perHostMeta modsModule rootModsModule coverageModule;
      hostCtx = mkHostContext (resolved // {workspaceMeta = perHostMeta;});
    in [
      {
        name = "${resolved.username}@${name}";
        value = home-manager.lib.homeManagerConfiguration {
          inherit (hostCtx) pkgs;
          extraSpecialArgs = {
            isNixOS = false;
            inherit inputs;
            inherit (hostCtx) metaConfig unstable unstable-fallback;
          };
          modules = [
            ./lib/workspace-options.nix
            {workspace = hostCtx.metaConfig;}
            ../mods/default.nix
            modsModule
            coverageModule
            (import hostCtx.homeConfig)
          ];
        };
      }
      {
        name = "root@${name}";
        value = home-manager.lib.homeManagerConfiguration {
          inherit (hostCtx) pkgs;
          extraSpecialArgs = {
            isNixOS = false;
            inherit inputs;
            metaConfig = hostCtx.metaConfig // {username = "root";};
            inherit (hostCtx) unstable unstable-fallback;
          };
          modules = [
            ./lib/workspace-options.nix
            {workspace = hostCtx.metaConfig // {username = "root";};}
            # gui/devel 설정 제외한 modsModule (옵션 선언은 mods/default.nix가 담당)
            rootModsModule
            ({
              options,
              lib,
              ...
            }:
              import ./lib/mk-preset.nix {
                inherit lib options;
                presetName = resolved.preset;
                presetsJsonPath = ../presets.json;
                # root는 sys 모듈만 활성화하므로 gui/devel 커버리지 제외
                excludePrefixes = ["mods.gui" "mods.devel"];
              })
            ../mods/default.nix
          ];
        };
      }
    ])
    hostNames);
}
