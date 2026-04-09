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

  outputs = inputs: (import ./flake.outputs.nix) inputs;
}
