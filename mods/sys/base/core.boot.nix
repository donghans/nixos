{mkPartOf, ...}:
mkPartOf "mods.sys.base" ({
  config,
  pkgs,
  lib,
  ...
}: let
  inherit (config.workspace) type;
  inherit (config.workspace) bootLoader;
  isRpi = type == "rpi";
  isBios = bootLoader == "grub-bios";
  isUefi = bootLoader == "grub-uefi";
  # EFI: desktop/laptop/server 로컬 기본값 (bootLoader="systemd-boot", 비-RPi)
  isEfi = !isRpi && bootLoader == "systemd-boot";
in {
  os = lib.mkMerge [
    # == EFI 시스템 (desktop / laptop / server 로컬) ==
    (lib.mkIf isEfi {
      boot = {
        loader.systemd-boot.enable = true;
        loader.efi.canTouchEfiVariables = true;
        loader.efi.efiSysMountPoint = "/boot";
        kernelPackages = pkgs.linuxPackages;
      };
    })

    # == BIOS (bootLoader="grub-bios") — GPT+EF02, GRUB BIOS 설치 ==
    # device는 disko GPT+EF02 설정이 자동 주입 — 여기서 중복 설정 불가
    (lib.mkIf isBios {
      boot = {
        loader.grub = {
          enable = true;
          efiSupport = false;
        };
        kernelPackages = pkgs.linuxPackages;
      };
    })

    # == UEFI (bootLoader="grub-uefi") — GRUB removable 경로 설치 ==
    # (목적: 가상화/클라우드 EFI처럼 펌웨어 직접 쓰기 불가한 환경)
    (lib.mkIf isUefi {
      boot = {
        loader.grub = {
          enable = true;
          device = "nodev";
          efiSupport = true;
          efiInstallAsRemovable = true;
        };
        loader.efi.canTouchEfiVariables = false;
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
