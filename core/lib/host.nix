{
  inputs,
  customOverlays,
}: let
  inherit (inputs) nixpkgs nixpkgs-unstable;

  # core/lib/mods.nix의 모듈 헬퍼 번들 — specialArgs로 전 모듈에 주입
  modsLib = import ./mods.nix {inherit (nixpkgs) lib;};
  inherit (modsLib) modArgs recursiveImportDir;

  # == Common Host Context Generator ==
  mkHostContext = hostInfo @ {
    hostname,
    system,
    type,
    workspaceMeta,
    ...
  }: let
    pkgsVersionClean = builtins.replaceStrings ["."] [""] workspaceMeta.pkgsVersion;
    selectedNixpkgs = inputs."nixpkgs-${pkgsVersionClean}" or inputs.nixpkgs;
    selectedHomeManager = inputs."home-manager-${pkgsVersionClean}" or inputs.home-manager;

    pkgs = import selectedNixpkgs {
      localSystem = system;
      config.allowUnfree = true;
      config.permittedInsecurePackages = [
        "electron-39.8.10"
        "docker-28.5.2"
        "incus-lts-6.0.6-unstable-2026-03-27"
        "incus-lts-client-6.0.6-unstable-2026-03-27"
      ];
      overlays = customOverlays;
    };

    unstable = import nixpkgs-unstable {
      localSystem = system;
      config.allowUnfree = true;
      config.permittedInsecurePackages = [
        "electron-39.8.10"
        "docker-28.5.2"
        "incus-lts-6.0.6-unstable-2026-03-27"
        "incus-lts-client-6.0.6-unstable-2026-03-27"
      ];
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
          config.permittedInsecurePackages = [
            "electron-39.8.10"
            "docker-28.5.2"
            "incus-lts-6.0.6-unstable-2026-03-27"
            "incus-lts-client-6.0.6-unstable-2026-03-27"
          ];
        }
      else unstable;

    # (목적: ISO 환경에서는 'nixos' 기본 유저 강제 사용)
    isISO = hostInfo.isISO or false;
    homeUser =
      if isISO
      then "nixos"
      else workspaceMeta.username;

    # 통합 호스트 파일(hosts/<hostname>.nix) 우선 탐색, 없으면 기존 경로로 fallback
    unifiedHostFile = ../../hosts/${hostname}.nix;
    hasUnifiedHost = builtins.pathExists unifiedHostFile;

    homeConfig =
      if isISO
      then ../iso.nix
      else if hasUnifiedHost
      then unifiedHostFile
      else ../../hosts/${hostname}/home.nix;

    metaConfig = {
      inherit (workspaceMeta) gitName gitEmail nixosRepo;
      inherit hostname type;
      username = homeUser;
      ramGb = hostInfo.ramGb       or null;
      swapGb = hostInfo.swapGb      or null;
      tmpfsSize = hostInfo.tmpfsSize   or null;
      zramPercent = hostInfo.zramPercent or null;
      bootLoader = hostInfo.bootLoader or "systemd-boot";
      isRemote = hostInfo.isRemote      or false;
      hasDeployRs = hostInfo.hasDeployRs  or false;
      cloudProvider = hostInfo.cloudProvider or null;
      diskDevice = hostInfo.diskDevice    or workspaceMeta.diskDevice;
      bootDevice = hostInfo.bootDevice    or workspaceMeta.bootDevice;
      timeZone = hostInfo.timeZone      or workspaceMeta.timeZone;
      defaultLocale = hostInfo.defaultLocale or workspaceMeta.defaultLocale;
      extraLocale = hostInfo.extraLocale   or workspaceMeta.extraLocale or null;
      inherit (workspaceMeta) stateVersion;
    };
  in {
    inherit homeUser homeConfig metaConfig unstable unstable-fallback pkgs;
    inherit hasUnifiedHost unifiedHostFile;
    inherit selectedNixpkgs selectedHomeManager;
  };

  # == Host Generator ==
  mkHost = hostInfo: let
    isISO = hostInfo.isISO or false;
    extraModules = hostInfo.extraModules or [];
    hmModules = hostInfo.hmModules    or [];
    hostCtx = mkHostContext (hostInfo // {inherit isISO;});

    # remote 호스트는 per-host hardware.nix(hosts/_deploy/<hostname>.hardware.nix)를 우선 사용.
    # 파일이 없거나 로컬 호스트이면 공용 hardware.nix(BUILD_DIR 루트)로 fallback.
    _isRemote = hostInfo.isRemote or false;
    _remoteHwPath = ../../hosts/_deploy/${hostInfo.hostname}.hardware.nix;
    _hwModule =
      if _isRemote && builtins.pathExists _remoteHwPath
      then _remoteHwPath
      else ../../hardware.nix;

    mainConfig =
      if isISO
      then [
        "${nixpkgs}/nixos/modules/installer/cd-dvd/installation-cd-graphical-base.nix"
        ../iso.nix
      ]
      else if hostCtx.hasUnifiedHost
      then [hostCtx.unifiedHostFile _hwModule]
      else [
        ../../hosts/${hostInfo.hostname}/configuration.nix
        _hwModule
      ];
  in
    hostCtx.selectedNixpkgs.lib.nixosSystem {
      specialArgs =
        {
          forOS = true;
          inherit isISO;
          inherit inputs;
          inherit (hostCtx) metaConfig;
          inherit (hostCtx) unstable;
          inherit (hostCtx) unstable-fallback;
        }
        // modArgs;

      modules =
        [{nixpkgs.hostPlatform = hostInfo.system;}]
        ++ mainConfig
        ++ [./workspace-options.nix]
        ++ [inputs.disko.nixosModules.disko]
        ++ recursiveImportDir ../../mods
        ++ [
          {
            workspace = hostCtx.metaConfig;
            nixpkgs.overlays = customOverlays;
            nixpkgs.config.allowUnfree = true;
            nixpkgs.config.permittedInsecurePackages = [
              "electron-39.8.10"
              "docker-28.5.2"
              "incus-lts-6.0.6-unstable-2026-03-27"
              "incus-lts-client-6.0.6-unstable-2026-03-27"
            ];

            # (목적: mkWrapper의 NIX_LD/NIX_LD_LIBRARY_PATH가 실제로 동작하기 위한 전제조건)
            # (이유: NixOS에 /lib64/ld-linux-x86-64.so.2 stub이 없으면 외부 바이너리가 실행 불가.
            #        라이브러리 버전은 programs.nix-ld.libraries가 아닌 mkWrapper libs로 프로그램별 관리.)
            programs.nix-ld.enable = true;

            # (목적: 전역 관리 CLI 'nixup' 시스템 등록 + man 페이지 설치)
            environment.systemPackages = let
              pkgs' = nixpkgs.legacyPackages.${hostInfo.system};
            in [
              (pkgs'.writeShellScriptBin "nixup" ''
                # nix-shell 진입(~8초) 전에 sudo 선취득
                _pf_has_build=false
                for _pf_arg in "$@"; do
                  case "$_pf_arg" in -b|--build) _pf_has_build=true; break ;; esac
                done
                _pf_needs_sudo=false
                case "''${1:-}" in
                  os|"")
                    [ "$_pf_has_build" = false ] && _pf_needs_sudo=true ;;
                  clean)
                    for _pf_arg in "$@"; do
                      case "$_pf_arg" in --all|-a) _pf_needs_sudo=true; break ;; esac
                    done ;;
                  -*)
                    [ "$_pf_has_build" = false ] && _pf_needs_sudo=true ;;
                esac
                if [ "$_pf_needs_sudo" = true ]; then
                  sudo -v
                fi
                unset _pf_needs_sudo _pf_has_build _pf_arg
                exec /etc/nixos/core/scripts/nixup.sh "$@"
              '')
              (pkgs'.writeShellScriptBin "rnixup" ''
                exec /etc/nixos/core/scripts/rnixup.sh "$@"
              '')
              (pkgs'.writeShellScriptBin "rnixstrap" ''
                exec /etc/nixos/core/scripts/rnixstrap.sh "$@"
              '')
              (pkgs'.writeShellScriptBin "nixsec" ''
                exec /etc/nixos/core/scripts/nixsec.sh "$@"
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

            # (목적: 원격 호스트 SSH — 서버 타입 공통)
            # (deploy-rs 호스트: root 키 전용 허용 — magic rollback 필요)
            # (standalone 서버: 부트스트랩 완료 후 root 접근 불필요 → "no")
            services.openssh = nixpkgs.lib.mkIf hostCtx.metaConfig.isRemote {
              enable = true;
              settings.PermitRootLogin =
                if hostCtx.metaConfig.hasDeployRs
                then "prohibit-password"
                else "no";
              # (pub key 없는 password-only 서버: core.network.nix의 false를 오버라이드해 비밀번호 SSH 허용)
              # (pub key 있는 경우: core.network.nix의 false가 그대로 적용됨)
              settings.PasswordAuthentication =
                nixpkgs.lib.mkIf (!(builtins.pathExists ../../hosts/_deploy/${hostInfo.hostname}.pub))
                (nixpkgs.lib.mkForce true);
            };

            # (목적: deploy-rs 호스트에만 root SSH 키 주입 — standalone은 root login 비활성화이므로 불필요)
            users.users.root.openssh.authorizedKeys.keyFiles =
              nixpkgs.lib.optional
              (hostCtx.metaConfig.hasDeployRs
                && builtins.pathExists ../../hosts/_deploy/${hostInfo.hostname}.pub)
              ../../hosts/_deploy/${hostInfo.hostname}.pub;

            # (목적: deploy-rs가 root로 nix copy 실행 — root는 기본 trusted-user)
            nix.settings.trusted-users =
              nixpkgs.lib.mkIf
              hostCtx.metaConfig.isRemote
              ["root"];

            # (목적: standalone 서버 — 원격 nixup os 실행 시 primary user sudo 비밀번호 불필요)
            # (이유: PermitRootLogin=no이므로 primary user + passwordless sudo가 유일한 원격 관리 경로)
            security.sudo.wheelNeedsPassword =
              nixpkgs.lib.mkIf
              (hostCtx.metaConfig.isRemote && !hostCtx.metaConfig.hasDeployRs)
              false;

            # (목적: 로컬 호스트 primary user — 신규 설치 시 빈 비밀번호로 첫 부팅 로그인 허용)
            # (이후 passwd 실행하면 shadow 갱신 — mutableUsers=true 기본값)
            # (ISO는 nixos 유저를 installation-cd-graphical-base.nix에서 별도 관리하므로 제외)
            users.users.${hostCtx.metaConfig.username} = nixpkgs.lib.mkIf (!hostCtx.metaConfig.isRemote && !isISO) {
              initialHashedPassword = "";
            };

            # (목적: nixup 로그 디렉터리 생성 및 쓰기 권한 부여)
            systemd.tmpfiles.rules = [
              "d /var/log/nixup 0775 ${
                if hostCtx.metaConfig.isRemote
                then "root"
                else hostCtx.metaConfig.username
              } users -"
            ];
          }
        ]
        # (목적: 원격 호스트 home-manager를 NixOS 모듈로 통합)
        # (이유: deploy-rs는 root로 실행하므로 standalone HM 활성화 시 USER 불일치 오류 발생)
        ++ nixpkgs.lib.optional hostCtx.metaConfig.isRemote
        {
          imports = [hostCtx.selectedHomeManager.nixosModules.home-manager];
          home-manager = {
            useGlobalPkgs = true;
            useUserPackages = true;
            extraSpecialArgs =
              {
                forOS = false;
                isISO = false;
                inherit inputs;
                inherit (hostCtx) metaConfig unstable unstable-fallback;
              }
              // modArgs;
            users.${hostCtx.metaConfig.username}.imports =
              [./workspace-options.nix {workspace = hostCtx.metaConfig;}]
              ++ recursiveImportDir ../../mods
              ++ hmModules
              ++ [(import hostCtx.homeConfig)];
          };
        }
        # (목적: ISO home-manager를 NixOS 모듈로 통합 — 'nixos' 유저에 Hyprland/zsh 설정 적용)
        # (이유: ISO는 standalone HM 없이 부팅되므로 NixOS 모듈로 통합해야 dotfile 생성됨)
        ++ nixpkgs.lib.optional isISO
        {
          imports = [hostCtx.selectedHomeManager.nixosModules.home-manager];
          home-manager = {
            useGlobalPkgs = true;
            useUserPackages = true;
            extraSpecialArgs =
              {
                forOS = false;
                isISO = true;
                inherit inputs;
                inherit (hostCtx) metaConfig unstable unstable-fallback;
              }
              // modArgs;
            users.${hostCtx.metaConfig.username}.imports =
              [./workspace-options.nix {workspace = hostCtx.metaConfig;}]
              ++ recursiveImportDir ../../mods
              ++ hmModules
              ++ [(import hostCtx.homeConfig)];
          };
        }
        # (목적: 원격 호스트 primary user 생성 + 콘솔 SSH 키 주입)
        # (별도 모듈로 분리: 같은 attrset 내 users.users.root.xxx 와 충돌 방지)
        ++ nixpkgs.lib.optional hostCtx.metaConfig.isRemote
        {
          users.users.${hostCtx.metaConfig.username} = {
            isNormalUser = true;
            extraGroups = ["wheel"];
            openssh.authorizedKeys.keyFiles =
              nixpkgs.lib.optional
              (builtins.pathExists ../../hosts/_deploy/${hostInfo.hostname}.pub)
              ../../hosts/_deploy/${hostInfo.hostname}.pub;
          };
        }
        ++ extraModules;
    };
in {
  inherit mkHostContext mkHost recursiveImportDir;
  inherit (modsLib) modArgs;
}
