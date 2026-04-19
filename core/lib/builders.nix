{
  inputs,
  customOverlays,
}: let
  inherit (inputs) nixpkgs nixpkgs-unstable home-manager;

  # == Common Host Context Generator ==
  mkHostContext = hostInfo @ {
    hostname,
    system,
    type,
    workspaceMeta,
    ...
  }: let
    pkgs = import nixpkgs {
      localSystem = system;
      config.allowUnfree = true;
      overlays = customOverlays;
    };

    unstable = import nixpkgs-unstable {
      localSystem = system;
      config.allowUnfree = true;
    };

    # .env 파일에서 특정 키의 값을 읽어오는 간단한 헬퍼
    getEnv = key: let
      envFile = ../../.env;
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

    envRev = getEnv "NIX_UNSTABLE_FALLBACK_REV";
    envSha = getEnv "NIX_UNSTABLE_FALLBACK_SHA";

    unstable-fallback =
      if (envRev != "" && envSha != "")
      then
        import (builtins.fetchTarball {
          url = "https://github.com/nixos/nixpkgs/archive/${envRev}.tar.gz";
          sha256 = envSha;
        }) {
          localSystem = system;
          config.allowUnfree = true;
        }
      else unstable;

    # (목적: ISO 환경에서는 'nixos' 기본 유저 강제 사용)
    isISO = hostInfo.isISO or false;
    homeUser =
      if isISO
      then "nixos"
      else workspaceMeta.username;

    homeConfig =
      if isISO
      then ../iso.home.nix
      else ../../hosts/${hostname}/home.nix;

    metaConfig = {
      inherit (workspaceMeta) gitName gitEmail nixosRepo;
      inherit hostname type;
      username = homeUser;
      ramGb = hostInfo.ramGb       or null;
      swapGb = hostInfo.swapGb      or null;
      tmpfsSize = hostInfo.tmpfsSize   or null;
      zramPercent = hostInfo.zramPercent or null;
      diskDevice = hostInfo.diskDevice    or workspaceMeta.diskDevice;
      bootDevice = hostInfo.bootDevice    or workspaceMeta.bootDevice;
      timeZone = hostInfo.timeZone      or workspaceMeta.timeZone;
      defaultLocale = hostInfo.defaultLocale or workspaceMeta.defaultLocale;
      extraLocale = hostInfo.extraLocale   or workspaceMeta.extraLocale or null;
      inherit (workspaceMeta) stateVersion;
    };
  in {
    inherit homeUser homeConfig metaConfig unstable unstable-fallback pkgs;
  };

  # == Host Generator ==
  mkHost = hostInfo: let
    isISO = hostInfo.isISO or false;
    extraModules = hostInfo.extraModules or [];
    hostCtx = mkHostContext (hostInfo // {inherit isISO;});

    mainConfig =
      if isISO
      then [
        "${nixpkgs}/nixos/modules/installer/cd-dvd/installation-cd-graphical-base.nix"
        ../iso.nix
      ]
      else [
        ../../hosts/${hostInfo.hostname}/configuration.nix
      ];
  in
    nixpkgs.lib.nixosSystem {
      specialArgs = {
        isNixOS = true;
        inherit inputs;
        inherit (hostCtx) metaConfig;
        inherit (hostCtx) unstable;
        inherit (hostCtx) unstable-fallback;
      };

      modules =
        [{nixpkgs.hostPlatform = hostInfo.system;}]
        ++ mainConfig
        ++ [
          ./workspace-options.nix
          ../../mods/default.nix
          {
            workspace = hostCtx.metaConfig;
            nixpkgs.overlays = customOverlays;
            nixpkgs.config.allowUnfree = true;

            # (목적: mkWrapper의 NIX_LD/NIX_LD_LIBRARY_PATH가 실제로 동작하기 위한 전제조건)
            # (이유: NixOS에 /lib64/ld-linux-x86-64.so.2 stub이 없으면 외부 바이너리가 실행 불가.
            #        라이브러리 버전은 programs.nix-ld.libraries가 아닌 mkWrapper libs로 프로그램별 관리.)
            programs.nix-ld.enable = true;

            # (목적: 전역 관리 CLI 'nixup' 시스템 등록 + man 페이지 설치)
            environment.systemPackages = let
              pkgs' = nixpkgs.legacyPackages.${hostInfo.system};
            in [
              (pkgs'.writeShellScriptBin "nixup" ''
                exec /etc/nixos/core/scripts/nixup.sh "$@"
              '')
              (pkgs'.runCommand "nixup-man" {} ''
                mkdir -p $out/share/man/man1
                cp ${../scripts/man/nixup.1} $out/share/man/man1/nixup.1
                gzip $out/share/man/man1/nixup.1
              '')
            ];

            # (목적: root 계정 잠금 — 패스워드 인증으로 직접 로그인 불가)
            # (ISO는 installation-cd-graphical-base.nix가 initialHashedPassword=""를 설정하므로 제외)
            # (wheel 그룹을 통해 sudo는 계속 사용 가능)
            users.users.root.hashedPassword = nixpkgs.lib.mkIf (!isISO) "!";

            # (목적: 신규 설치 시 shadow 항목이 없으면 빈 비밀번호로 첫 부팅 로그인 허용)
            # (이후 사용자가 passwd 실행하면 shadow가 갱신되어 이 설정은 무시됨 — mutableUsers=true 기본값)
            # (ISO는 nixos 유저를 installation-cd-graphical-base.nix에서 별도 관리하므로 제외)
            users.users.${hostCtx.metaConfig.username}.initialHashedPassword =
              nixpkgs.lib.mkIf (!isISO) "";

            # (목적: nixup 로그 디렉터리 생성 및 쓰기 권한 부여)
            systemd.tmpfiles.rules = [
              "d /var/log/nixup 0775 ${hostCtx.metaConfig.username} users -"
            ];
          }
        ]
        ++ extraModules
        ++ [
          home-manager.nixosModules.home-manager
          {
            home-manager.sharedModules =
              [
                ./workspace-options.nix
                ../../mods/default.nix
                {workspace = hostCtx.metaConfig;}
              ]
              ++ extraModules;
            home-manager.useGlobalPkgs = true;
            home-manager.useUserPackages = true;

            # (목적: 기존 설정과 충돌 시 파일 백업 생성)
            home-manager.backupFileExtension = "backup";
            home-manager.users.${hostCtx.homeUser} = import hostCtx.homeConfig;
            home-manager.users.root = import ../../mods/sys/base/home.nix;
            home-manager.extraSpecialArgs = {
              isNixOS = false;
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
