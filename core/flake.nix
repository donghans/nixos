{
  description = "Modular NixOS Framework: A data-driven orchestrator for multi-host and ISO configurations.";

  inputs = {
    # == Input Channels ==
    nixpkgs-unstable.url = "github:nixos/nixpkgs/nixos-unstable";

    nixpkgs.url      =                "github:nixos/nixpkgs/nixos-25.11";
    home-manager.url = "github:nix-community/home-manager/release-25.11";

    # (목적: HM이 시스템과 동일한 Nixpkgs 버전을 사용하도록 강제)
    home-manager.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs = {
    nixpkgs,
    home-manager,
    ...
  } @ inputs: let
    # == Overlays ==
    customOverlays = [
      (import ./lib/mk-wrapper.nix)
    ];

    # == Metadata Import ==
    # (목적: 격리 빌드 시 제공되는 단일 진실 공급원 로드)
    infoPath = ./hosts/_info.json;
    workspaceMetaRaw = builtins.fromJSON (builtins.readFile infoPath);
    defaultStateVersion = "25.11"; # 기본 버전
    workspaceMeta =
      workspaceMetaRaw
      // {
        gitName = workspaceMetaRaw.git.name;
        gitEmail = workspaceMetaRaw.git.email;
        inherit (workspaceMetaRaw.git) nixosRepo;
        stateVersion = workspaceMetaRaw.stateVersion or defaultStateVersion;
      };
    inherit (workspaceMeta) hosts;

    # == Builders ==
    builders = import ./lib/builders.nix {
      inherit inputs workspaceMeta customOverlays;
    };
    inherit (builders) mkHost mkHostContext;
  in {
    # == Output: NixOS Configurations ==
    nixosConfigurations =
      (nixpkgs.lib.genAttrs
        (map (hostCtx: hostCtx.hostname) hosts)
        (name: let
          hostInfo = builtins.head (builtins.filter (hostCtx: hostCtx.hostname == name) hosts);
        in
          mkHost hostInfo))
      // {
        custom-iso = mkHost {
          hostname = "nixos-iso";
          system = "x86_64-linux";
          isLaptop = false;
          isISO = true;
        };
      };

    # == Output: Home Configurations ==
    homeConfigurations = builtins.listToAttrs (nixpkgs.lib.concatMap (hostInfo: let
        hostCtx = mkHostContext hostInfo;
      in [
        {
          name = "${hostCtx.metaConfig.username}@${hostInfo.hostname}";
          value = home-manager.lib.homeManagerConfiguration {
            inherit (hostCtx) pkgs;
            extraSpecialArgs = {
              isNixOS = false;
              inherit inputs;
              inherit (hostCtx) metaConfig;
              inherit (hostCtx) unstable;
              inherit (hostCtx) unstable-fallback;
            };
            modules = [
              ./lib/workspace-options.nix
              {workspace = hostCtx.metaConfig;}
              ./mods/default.nix
              (import hostCtx.homeConfig)
            ];
          };
        }
        {
          name = "root@${hostInfo.hostname}";
          value = home-manager.lib.homeManagerConfiguration {
            inherit (hostCtx) pkgs;
            extraSpecialArgs = {
              isNixOS = false;
              inherit inputs;
              metaConfig = hostCtx.metaConfig // {username = "root";};
              inherit (hostCtx) unstable;
              inherit (hostCtx) unstable-fallback;
            };
            modules = [
              ./lib/workspace-options.nix
              {workspace = hostCtx.metaConfig // {username = "root";};}
              (import ./mods/sys/default.nix)
            ];
          };
        }
      ])
      hosts);
  };
}
