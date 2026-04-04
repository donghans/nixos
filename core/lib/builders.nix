{
  inputs,
  workspaceMeta,
  customOverlays,
}: let
  inherit (inputs) nixpkgs nixpkgs-unstable home-manager;

  # == Common Host Context Generator ==
  mkHostContext = {
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
      overlays = customOverlays;
    };

    unstable = import nixpkgs-unstable {
      inherit system;
      config.allowUnfree = true;
    };

    # .env 파일에서 특정 키의 값을 읽어오는 간단한 헬퍼
    getEnv = key: let
      envFile = ../.env;
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
    homeUser =
      if isISO
      then "nixos"
      else workspaceMeta.username;

    homeConfig =
      if isISO
      then ../iso.home.nix
      else ../dev/${hostname}.home.nix;

    metaConfig = {
      inherit (workspaceMeta) gitName gitEmail nixosRepo stateVersion;
      inherit hostname isLaptop ramGb;
      username = homeUser;
    };
  in {
    inherit homeUser homeConfig metaConfig unstable unstable-fallback pkgs;
  };

  # == Host Generator ==
  mkHost = hostInfo: let
    isISO = hostInfo.isISO or false;
    hostCtx = mkHostContext (hostInfo // {inherit isISO;});

    mainConfig =
      if isISO
      then [
        "${nixpkgs}/nixos/modules/installer/cd-dvd/installation-cd-graphical-base.nix"
        ../iso.nix
      ]
      else [
        ../dev/${hostInfo.hostname}.nix
      ];
  in
    nixpkgs.lib.nixosSystem {
      inherit (hostInfo) system;
      specialArgs = {
        inherit inputs;
        inherit (hostCtx) metaConfig;
        inherit (hostCtx) unstable;
        inherit (hostCtx) unstable-fallback;
      };

      modules =
        mainConfig
        ++ [
          {
            nixpkgs.overlays = customOverlays;
            nixpkgs.config.allowUnfree = true;

            # (목적: 전역 관리 CLI 'nhw' 시스템 등록)
            environment.systemPackages = [
              (nixpkgs.legacyPackages.${hostInfo.system}.writeShellScriptBin "nhw" ''
                exec /home/${workspaceMeta.username}/nixos/core/scripts/nhw.sh "$@"
              '')
            ];

            # (목적: nhw 로그 디렉터리 생성 및 쓰기 권한 부여)
            systemd.tmpfiles.rules = [
              "d /var/log/nhw 0775 ${workspaceMeta.username} users -"
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
            home-manager.users.${hostCtx.homeUser} = import hostCtx.homeConfig;
            home-manager.extraSpecialArgs = {
              inherit inputs;
              inherit (hostCtx) metaConfig;
              inherit (hostCtx) unstable;
              inherit (hostCtx) unstable-fallback;
            };
          }
        ];
    };
in {
  inherit mkHostContext mkHost;
}
