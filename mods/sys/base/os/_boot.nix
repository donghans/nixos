{pkgs, ...}: {
  # == Boot Loader ==
  # (목적: rEFInd 호환성을 위한 시스템디 부트 최소 설정)
  boot = {
    loader.systemd-boot.enable = true;
    loader.efi.canTouchEfiVariables = true;
    loader.efi.efiSysMountPoint = "/boot";
    kernelPackages = pkgs.linuxPackages;
  };
}
