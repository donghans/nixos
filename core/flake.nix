{
  description = "My First NixOS Flake Configuration";

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
    nixpkgs-unstable,
    home-manager,
    ...
  } @ inputs: let
    stateVersion = "25.11";

    myOverlays = [
      (_self: super: {
        mkWrapper = {
          pkg,
          name ? "${pkg.name}-wrapped",
          binName ? "*",
          libs ? [],
          env ? {},
          addFlags ? [],
          run ? null,
          bins ? [],
        }:
          super.symlinkJoin {
            inherit name;
            paths = [pkg];
            nativeBuildInputs = [super.makeWrapper];
            postBuild = let
              ldPath = super.lib.makeLibraryPath libs;

              argsList =
                (super.lib.optionals (libs != []) [
                  ''--set NIX_LD_LIBRARY_PATH "${ldPath}"''
                  ''--set NIX_LD "${super.stdenv.cc.bintools.dynamicLinker}"''
                ])
                ++ (super.lib.optionals (bins != []) [
                  ''--prefix PATH : "${super.lib.makeBinPath bins}"''
                ])
                ++ (super.lib.mapAttrsToList (k: v: "--set ${k} ${super.lib.escapeShellArg v}") env)
                ++ (super.lib.optionals (run != null) [
                  "--run ${super.lib.escapeShellArg run}"
                ])
                ++ (super.lib.optionals (addFlags != []) [
                  "--add-flags ${super.lib.escapeShellArg (super.lib.concatStringsSep " " (map super.lib.escapeShellArg addFlags))}"
                ]);

              bashArgs = super.lib.concatStringsSep " \\\n  " argsList;
            in ''
              ${super.lib.optionalString (builtins.length argsList > 0) ''
                if [ "${binName}" = "*" ]; then
                  for bin in $out/bin/*; do
                    if [ -f "$bin" ]; then
                      wrapProgram "$bin" \
                        ${bashArgs}
                    fi
                  done
                else
                  wrapProgram "$out/bin/${binName}" \
                    ${bashArgs}
                fi
              ''}
            '';
          };
      })
    ];

    # == Metadata Import ==
    # (목적: 격리 빌드 시 제공되는 단일 진실 공급원 로드)
    infoPath = ./dev/_info.json;
    info = builtins.fromJSON (builtins.readFile infoPath);

    gitName = info.git.name;
    gitEmail = info.git.email;
    inherit (info.git) nixosRepo;
    inherit (info) hosts;

    # == Common HM Generator ==
    getHM = {
      hostname,
      system,
      isLaptop,
      ramGb ? null,
      isISO ? false,
      ...
    }: let
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
        overlays = myOverlays;
      };

      unstable = import nixpkgs-unstable {
        inherit system;
        config.allowUnfree = true;
      };

      # .env 파일에서 특정 키의 값을 읽어오는 간단한 헬퍼
      getEnv = key: let
        envFile = ./.env;
        content =
          if builtins.pathExists envFile
          then builtins.readFile envFile
          else "";
        lines = nixpkgs.lib.splitString "\n" content;
        line = nixpkgs.lib.findFirst (l: nixpkgs.lib.hasPrefix "${key}=" l) "" lines;
      in
        if line != ""
        then nixpkgs.lib.removePrefix "${key}=" line
        else "";

      envRev = getEnv "UNSTABLE_FALLBACK_REV";
      envSha = getEnv "UNSTABLE_FALLBACK_SHA";

      unstable-fallback =
        if (envRev != "" && envSha != "")
        then
          import (builtins.fetchTarball {
            url = "https://github.com/nixos/nixpkgs/archive/${envRev}.tar.gz";
            sha256 = envSha;
          }) {
            inherit system;
            config.allowUnfree = true;
          }
        else unstable;

      # (목적: ISO 환경에서는 'nixos' 기본 유저 강제 사용)
      hmUser =
        if isISO
        then "nixos"
        else info.username;
      hmConfig =
        if isISO
        then ./iso.home.nix
        else ./dev/${hostname}.home.nix;

      metaConfig = {
        inherit stateVersion gitName gitEmail nixosRepo hostname isLaptop ramGb;
        username = hmUser;
      };
    in {
      inherit hmUser hmConfig metaConfig unstable unstable-fallback pkgs;
    };

    # == Host Generator ==
    mkHost = hostInfo: let
      isISO = hostInfo.isISO or false;
      h = getHM (hostInfo // {inherit isISO;});

      mainConfig =
        if isISO
        then [
          "${nixpkgs}/nixos/modules/installer/cd-dvd/installation-cd-graphical-base.nix"
          ./iso.nix
        ]
        else [
          ./dev/${hostInfo.hostname}.nix
        ];
    in
      nixpkgs.lib.nixosSystem {
        inherit (hostInfo) system;
        specialArgs = {
          inherit inputs;
          inherit (h) metaConfig;
          inherit (h) unstable;
          inherit (h) unstable-fallback;
        };

        modules =
          mainConfig
          ++ [
            {
              nixpkgs.overlays = myOverlays;
              nixpkgs.config.allowUnfree = true;

              # (목적: 전역 관리 CLI 'nhw' 시스템 등록)
              environment.systemPackages = [
                (nixpkgs.legacyPackages.${hostInfo.system}.writeShellScriptBin "nhw" ''
                  exec /home/${info.username}/nixos/core/scripts/nhw.sh "$@"
                '')
              ];

              # (목적: nhw 로그 디렉터리 생성 및 쓰기 권한 부여)
              systemd.tmpfiles.rules = [
                "d /var/log/nhw 0775 ${info.username} users -"
              ];
            }
          ]
          ++ [
            home-manager.nixosModules.home-manager
            {
              home-manager.useGlobalPkgs = true;
              home-manager.useUserPackages = true;

              # (목적: 기존 설정과 충돌 시 파일 백업 생성)
              home-manager.backupFileExtension = "backup";
              home-manager.users.${h.hmUser} = import h.hmConfig;
              home-manager.extraSpecialArgs = {
                inherit inputs;
                inherit (h) metaConfig;
                inherit (h) unstable;
                inherit (h) unstable-fallback;
              };
            }
          ];
      };
  in {
    # == Output: NixOS Configurations ==
    nixosConfigurations =
      (nixpkgs.lib.genAttrs
        (map (h: h.hostname) hosts)
        (name: let
          hostInfo = builtins.head (builtins.filter (h: h.hostname == name) hosts);
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
    homeConfigurations = builtins.listToAttrs (map (hostInfo: let
        h = getHM hostInfo;
      in {
        name = "${h.metaConfig.username}@${hostInfo.hostname}";
        value = home-manager.lib.homeManagerConfiguration {
          inherit (h) pkgs;
          extraSpecialArgs = {
            inherit inputs;
            inherit (h) metaConfig;
            inherit (h) unstable;
            inherit (h) unstable-fallback;
          };
          modules = [(import h.hmConfig)];
        };
      })
      hosts);
  };
}
