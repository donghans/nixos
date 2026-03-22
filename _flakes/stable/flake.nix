{
  description = "My First NixOS Flake Configuration";

  inputs = {
    # 최신 패키지를 위한 Unstable 채널
    nixpkgs-unstable.url = "github:nixos/nixpkgs/nixos-unstable";

    # 기본 패키지에 사용될 Stable 채널
    nixpkgs.url      =                "github:nixos/nixpkgs/nixos-25.11"; # 1. 패키지 저장소 박제
    home-manager.url = "github:nix-community/home-manager/release-25.11"; # 2. Home-manager 박제 (채널 대신 여기서 직접 가져옴)

    home-manager.inputs.nixpkgs.follows = "nixpkgs"; # HM이 시스템과 같은 Nix 패키지 버전을 쓰도록 강제
  };

  outputs = { self, nixpkgs, nixpkgs-unstable, home-manager, ... }@inputs: let
    # 1. 경로 후보 정의
    primaryInfoPath = ../../dev/_info.json;  # 일반 nh 빌드 시 (flake 위치 기준)
    isoInfoPath = ./_info.json;             # iso.sh 빌드 시 (hardlink된 위치 기준)

    # 2. 파일 존재 여부에 따라 경로 선택
    chosenInfoPath = if builtins.pathExists primaryInfoPath
      then primaryInfoPath
      else isoInfoPath;

    # 3. JSON 파일 읽기
    info = builtins.fromJSON (builtins.readFile chosenInfoPath);

    stateVersion = "25.11";
    gitName = info.git.name;
    gitEmail = info.git.email;
    username = info.username;

    # [수정] JSON에서 직접 hosts 리스트 추출
    hosts = info.hosts;

    # 설정 생성 헬퍼 함수
    mkHost = { hostname, system, isLaptop, isISO ? false }: let
      unstable = import nixpkgs-unstable { inherit system; config.allowUnfree = true; };
      metaConfig = { inherit stateVersion gitName gitEmail username hostname isLaptop; };

      # 호스트별 디렉토리 경로 동적 지정
      mainConfig = if isISO then [
        "${nixpkgs}/nixos/modules/installer/cd-dvd/installation-cd-graphical-base.nix"
        ./configuration.nix
      ] else [
        # 일반 호스트는 dev 디렉토리의 파일을 참조
        ../../dev/${hostname}.nix
      ];

      hmUser = if isISO then "root" else username;
      hmConfig = if isISO then ./home.nix else ../../dev/${hostname}.home.nix;
    in
      nixpkgs.lib.nixosSystem {
        inherit system;
        specialArgs = { inherit inputs metaConfig unstable; };

        modules = mainConfig ++ [
          home-manager.nixosModules.home-manager {
            home-manager.useGlobalPkgs = true;
            home-manager.useUserPackages = true;

            # 기존에 다른 configuration으로 NixOS를 사용하다 중간에 해당 nixos configuration을 적용시켰을 때 기존 설정값을 복원가능하도록 백업해두는 옵션
            home-manager.backupFileExtension = "backup";
            home-manager.users.${hmUser} = import hmConfig;
            home-manager.extraSpecialArgs = { inherit inputs metaConfig unstable; };
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
  };
}
