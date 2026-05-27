# EC2 t4g.micro (aarch64 Graviton) 하드웨어 설정
# nixos-generate-config 결과 기준 — 실설치 후 nixup 자동 갱신됨
{ config, lib, pkgs, modulesPath, ... }:
{
  imports = [];

  boot.initrd.availableKernelModules = [ "nvme" ];
  boot.initrd.kernelModules          = [];
  boot.kernelModules                 = [ "ena" ];
  boot.extraModulePackages           = [];

  networking.useDHCP = lib.mkDefault true;

  nixpkgs.hostPlatform = lib.mkDefault "aarch64-linux";
}
