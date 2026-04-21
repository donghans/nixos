{mkPartOf, ...}:
mkPartOf "mods.sys.base" ({
  config,
  pkgs,
  lib,
  ...
}: let
  inherit (config.workspace) type;
  inherit (config.workspace) bootTarget;
  isRpi = type == "rpi";
  isCloudBios = bootTarget == "cloud-bios";
  isCloudUefi = bootTarget == "cloud-uefi";
  # EFI: desktop/laptop/server 로컬 기본값 (bootTarget=null, 비-RPi)
  isEfi = !isRpi && !isCloudBios && !isCloudUefi;
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

    # == BIOS-only 클라우드 (Lightsail 등 — GPT+EF02) ==
    # (목적: Lightsail 인스턴스는 EFI 미지원 → GRUB BIOS 설치)
    # device는 disko GPT+EF02 설정이 자동 주입 — 여기서 중복 설정 불가
    (lib.mkIf isCloudBios {
      boot = {
        loader.grub = {
          enable = true;
          efiSupport = false;
        };
        kernelPackages = pkgs.linuxPackages;
      };
    })

    # == EFI 클라우드 (canTouchEfiVariables 금지) ==
    # (목적: 가상화 EFI — GRUB removable 경로 설치, 펌웨어 직접 쓰기 불가)
    (lib.mkIf isCloudUefi {
      boot = {
        loader.grub = {
          enable = true;
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
