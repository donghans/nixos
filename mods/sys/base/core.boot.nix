{mkPartOf, ...}:
mkPartOf "mods.sys.base" ({
  config,
  pkgs,
  lib,
  ...
}: let
  isRpi = config.workspace.type == "rpi";
in {
  os = lib.mkMerge [
    # == EFI 시스템 (desktop / laptop / server) ==
    (lib.mkIf (!isRpi) {
      boot = {
        loader.systemd-boot.enable = true;
        loader.efi.canTouchEfiVariables = true;
        loader.efi.efiSysMountPoint = "/boot";
        kernelPackages = pkgs.linuxPackages;
      };
    })
    # == Raspberry Pi (extlinux) ==
    # (목적: RPi는 EFI 미지원으로 generic-extlinux-compatible 사용)
    # (참고: 커널 및 펌웨어 세부 설정은 호스트별 _hardware.nix에서 override)
    (lib.mkIf isRpi {
      boot = {
        loader.grub.enable = false;
        loader.generic-extlinux-compatible.enable = true;
        kernelPackages = pkgs.linuxPackages;
      };
    })
  ];
})
