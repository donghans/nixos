# [주의] 이 파일은 placeholder입니다.
# 실제 설치 시 nixos-generate-config가 생성한 파일로 교체됩니다.
{
  lib,
  modulesPath,
  ...
}: {
  imports = [(modulesPath + "/installer/scan/not-detected.nix")];

  boot.initrd.availableKernelModules = ["xhci_pci" "usbhid" "usb_storage"];
  boot.kernelModules = [];

  nixpkgs.hostPlatform = lib.mkDefault "aarch64-linux";
}
