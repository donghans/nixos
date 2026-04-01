{
  description = "My First NixOS Flake Configuration";

  inputs = {
    # 최신 패키지를 위한 Unstable 채널
    nixpkgs-unstable.url = "github:nixos/nixpkgs/nixos-unstable";

    # 기본 패키지에 사용될 Stable 채널
    nixpkgs.url      =                "github:nixos/nixpkgs/nixos-25.11"; # 1. 패키지 저장소 박제
    nixpkgs-2405.url =                "github:nixos/nixpkgs/nixos-24.05"; # 2. Prisma 5 등 이전 패키지를 사용하기 위한 패키지 저장소
    home-manager.url = "github:nix-community/home-manager/release-25.11"; # 3. Home-manager 박제 (채널 대신 여기서 직접 가져옴)

    home-manager.inputs.nixpkgs.follows = "nixpkgs"; # HM이 시스템과 같은 Nix 패키지 버전을 쓰도록 강제
  };

  outputs = { self, nixpkgs, nixpkgs-2405, nixpkgs-unstable, home-manager, ... }@inputs: let
    stateVersion = "25.11";

    myOverlays = [
      (self: super: {
        mkNixLDWrapper = pkg: libs: super.symlinkJoin {
          name = "${pkg.name}-nix-ld";
          paths = [ pkg ];
          nativeBuildInputs = [ super.makeWrapper ];
          postBuild = ''
            for bin in $out/bin/*; do
              wrapProgram "$bin" \
                --set NIX_LD_LIBRARY_PATH "${super.lib.makeLibraryPath libs}" \
                --set NIX_LD "${super.stdenv.cc.bintools.dynamicLinker}"
            done
          '';
        };
      })
    ];

    # 1. 경로 후보 정의
    primaryInfoPath = ../../dev/_info.json;  # 일반 nh 빌드 시 (flake 위치 기준)
    isoInfoPath = ./_info.json;             # iso.sh 빌드 시 (hardlink된 위치 기준)

    # 2. 파일 존재 여부에 따라 경로 선택
    chosenInfoPath = if builtins.pathExists primaryInfoPath
      then primaryInfoPath
      else isoInfoPath;

    # 3. JSON 파일 읽기
    info = builtins.fromJSON (builtins.readFile chosenInfoPath);

    gitName = info.git.name;
    gitEmail = info.git.email;
    hosts = info.hosts;

    # [핵심] Home Manager 설정을 만드는 공통 함수
    getHM = { hostname, system, isLaptop, isISO ? false }: let
      pkgs = import nixpkgs {
        inherit system;
        config.allowUnfree = true;
        overlays = myOverlays;
      };

      unstable = import nixpkgs-unstable { inherit system; config.allowUnfree = true; };

      # ISO 부팅일 때만 유저명을 "nixos"로 고정
      hmUser = if isISO then "nixos" else info.username;
      hmConfig = if isISO then ./home.nix else ../../dev/${hostname}.home.nix;

      metaConfig = {
        inherit stateVersion gitName gitEmail hostname isLaptop;
        username = hmUser;
      };
    in {
      inherit hmUser hmConfig metaConfig unstable pkgs;
    };

    # 설정 생성 헬퍼 함수
    mkHost = hostInfo: let
      isISO = hostInfo.isISO or false;
      h = getHM (hostInfo // { inherit isISO; }); # 위에서 만든 공통 설정을 가져옴

      mainConfig = if isISO then [ # 호스트별 디렉토리 경로 동적 지정
        "${nixpkgs}/nixos/modules/installer/cd-dvd/installation-cd-graphical-base.nix"
        ./configuration.nix
      ] else [
        # 일반 호스트는 dev 디렉토리의 파일을 참조
        ../../dev/${hostInfo.hostname}.nix
      ];
    in nixpkgs.lib.nixosSystem {
      inherit (hostInfo) system;
      specialArgs = {
        inherit inputs;
        metaConfig = h.metaConfig;
        unstable = h.unstable;
      };

      modules = mainConfig ++ [{
        nixpkgs.overlays = myOverlays;
        nixpkgs.config.allowUnfree = true;
      }] ++ [
        home-manager.nixosModules.home-manager {
          home-manager.useGlobalPkgs = true;
          home-manager.useUserPackages = true;

          # 기존에 다른 configuration으로 NixOS를 사용하다 중간에 해당 nixos configuration을 적용시켰을 때 기존 설정값을 복원가능하도록 백업해두는 옵션
          home-manager.backupFileExtension = "backup";
          home-manager.users.${h.hmUser} = import h.hmConfig;
          home-manager.extraSpecialArgs = {
            inherit inputs;
            metaConfig = h.metaConfig;
            unstable = h.unstable;
          };
        }
      ];
    };
  in {
    # JSON의 hosts 리스트를 AttrSet으로 자동 변환
    nixosConfigurations = (nixpkgs.lib.genAttrs
      (map (h: h.hostname) hosts)
      (name: let
        # JSON 리스트에서 현재 호스트의 상세 객체(system, isLaptop 등)를 찾아 전달
        hostInfo = builtins.head (builtins.filter (h: h.hostname == name) hosts);
      in mkHost hostInfo)) // { # ISO 빌드용 타겟 (수동 추가 유지)
        custom-iso = mkHost {
          hostname = "nixos-iso";
          system = "x86_64-linux";
          isLaptop = false;
          isISO = true;
        };
      };

    # Home Manager 독립 설정 (nh home switch)
    homeConfigurations = builtins.listToAttrs (map (hostInfo: let
      h = getHM hostInfo;
    in {
      name = "${h.metaConfig.username}@${hostInfo.hostname}"; # 키 이름을 "유저명@호스트명" 형식으로 생성
      value = home-manager.lib.homeManagerConfiguration {
        inherit (h) pkgs;
        extraSpecialArgs = {
          inherit inputs;
          metaConfig = h.metaConfig;
          unstable = h.unstable;
        };
        modules = [ (import h.hmConfig) ];
      };
    }) hosts);
  };
}
