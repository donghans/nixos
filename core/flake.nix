{
  description = "Modular NixOS Framework: A data-driven orchestrator for multi-host and ISO configurations.";

  inputs = {
    # == Input Channels ==
    nixpkgs-unstable.url = "github:nixos/nixpkgs/nixos-unstable";

    # == Stable Channels (pkgsVersion mapping) ==
    nixpkgs-2511.url = "github:nixos/nixpkgs/nixos-25.11";
    home-manager-2511.url = "github:nix-community/home-manager/release-25.11";
    home-manager-2511.inputs.nixpkgs.follows = "nixpkgs-2511";

    nixpkgs-2605.url = "github:nixos/nixpkgs/nixos-26.05";
    home-manager-2605.url = "github:nix-community/home-manager/release-26.05";
    home-manager-2605.inputs.nixpkgs.follows = "nixpkgs-2605";

    nixpkgs.url      =                "github:nixos/nixpkgs/nixos-26.05";
    home-manager.url = "github:nix-community/home-manager/release-26.05";

    # (목적: HM이 시스템과 동일한 Nixpkgs 버전을 사용하도록 강제)
    home-manager.inputs.nixpkgs.follows = "nixpkgs";

    # (목적: 선언적 디스크 파티셔닝 — nixos-anywhere 초기 설치 시 사용)
    disko.url = "github:nix-community/disko";
    disko.inputs.nixpkgs.follows = "nixpkgs";

    # (목적: 원격 NixOS 시스템 배포 — nixup deploy 서브커맨드)
    deploy-rs.url = "github:serokell/deploy-rs";
    deploy-rs.inputs.nixpkgs.follows = "nixpkgs";
  };

  # (목적: nixup은 빌드 시 이 파일을 .build/flake.nix(루트)로 복사하므로,
  #         ./core/flake.outputs.nix는 .build/core/flake.outputs.nix를 가리킨다.
  #         원본 위치(core/flake.nix)에서 보면 경로가 이상해 보이지만 의도된 설계임.)
  outputs = inputs: (import ./core/flake.outputs.nix) inputs;
}
