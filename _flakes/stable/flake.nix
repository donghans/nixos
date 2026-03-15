{
  description = "My First NixOS Flake Configuration";

  inputs = {
    nixpkgs.url      =                "github:nixos/nixpkgs/nixos-25.11"; # 1. 패키지 저장소 박제
    home-manager.url = "github:nix-community/home-manager/release-25.11"; # 2. Home-manager 박제 (채널 대신 여기서 직접 가져옴)

    home-manager.inputs.nixpkgs.follows = "nixpkgs"; # HM이 시스템과 같은 Nix 패키지 버전을 쓰도록 강제
  };

  outputs = { self, nixpkgs, home-manager, ... }@inputs: let
    stateVersion = "25.11";

    gitName = "donghans";
    gitEmail = "78710114+donghans@users.noreply.github.com";

    username = "donghans";
    hosts = [
      { hostname = "beelink-ser7-co"; system = "x86_64-linux"; isLaptop = false; }
      { hostname = "msi-summit-me";   system = "x86_64-linux"; isLaptop = true;  }
    ];

    # 설정 생성 헬퍼 함수 (재사용 가능한 팩토리 함수)
    mkHost = { hostname, system, isLaptop }: let
      metaConfig = { inherit stateVersion gitName gitEmail username hostname isLaptop; };
    in
      nixpkgs.lib.nixosSystem {
        inherit system;
        specialArgs = { inherit inputs metaConfig; };

        modules = [
          # 호스트별 디렉토리 경로 동적 지정
          ../../dev/${hostname}/configuration.nix

          home-manager.nixosModules.home-manager {
            home-manager.useGlobalPkgs = true;
            home-manager.useUserPackages = true;

            # 기존에 다른 configuration으로 NixOS를 사용하다 중간에 해당 nixos configuration을 적용시켰을 때 기존 설정값을 복원가능하도록 백업해두는 옵션
            home-manager.backupFileExtension = "backup";

            home-manager.users.${username} = import ../../dev/${hostname}/home.nix;
            home-manager.extraSpecialArgs = { inherit inputs metaConfig; };
          }
        ];
      };
  in {
    # "For loop" 핵심 부분: 리스트를 AttrSet으로 변환
    # hosts 리스트를 돌면서 { "msi-summit.me" = mkHost ... } 형태의 세트를 만듭니다.
    nixosConfigurations = nixpkgs.lib.genAttrs
      (map (h: h.hostname) hosts)
      (name: let
        # 리스트에서 현재 이름에 맞는 호스트 정보를 찾아 mkHost에 전달
        hostInfo = builtins.head (builtins.filter (h: h.hostname == name) hosts);
      in mkHost hostInfo);
  };
}
