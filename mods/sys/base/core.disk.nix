{mkPartOf, ...}:
mkPartOf "mods.sys.base" ({
  pkgs,
  config,
  lib,
  ...
}: let
  inherit (config.workspace) bootLoader;
  inherit (config.workspace) diskDevice;
  isRpi = config.workspace.type == "rpi";

  btrfsOpts = subvol: [
    "subvol=${subvol}"
    "compress=zstd:3"
    "noatime"
    "discard=async"
    "space_cache=v2"
  ];

  btrfsSubvols = {
    "@" = {
      mountpoint = "/";
      mountOptions = btrfsOpts "@";
    };
    "@home" = {
      mountpoint = "/home";
      mountOptions = btrfsOpts "@home";
    };
    "@nix" = {
      mountpoint = "/nix";
      mountOptions = btrfsOpts "@nix";
    };
    "@log" = {
      mountpoint = "/var/log";
      mountOptions = btrfsOpts "@log";
    };
  };
in {
  os = lib.mkMerge [
    # == 로컬 호스트 (bootLoader="systemd-boot", 비-RPi) — 수동 fileSystems 선언 ==
    (lib.mkIf (bootLoader == "systemd-boot" && !isRpi) {
      fileSystems."/boot" = {
        device = config.workspace.bootDevice;
        fsType = "vfat";
        options = ["fmask=0137" "dmask=0027"];
      };

      fileSystems."/" = {
        device = diskDevice;
        fsType = "btrfs";
        options = btrfsOpts "@";
      };
      fileSystems."/home" = {
        device = diskDevice;
        fsType = "btrfs";
        options = btrfsOpts "@home";
      };
      fileSystems."/nix" = {
        device = diskDevice;
        fsType = "btrfs";
        options = btrfsOpts "@nix";
      };
      fileSystems."/var/log" = {
        device = diskDevice;
        fsType = "btrfs";
        options = btrfsOpts "@log";
      };

      services.btrfs.autoScrub = {
        enable = true;
        interval = "weekly";
        fileSystems = ["/"];
      };
      services.fstrim.enable = true;

      environment.systemPackages = with pkgs; [btrfs-progs];
    })

    # == 원격 호스트 (bootLoader="grub-bios") — disko가 파티셔닝 + fileSystems 담당 ==
    (lib.mkIf (bootLoader == "grub-bios") {
      disko.devices.disk.main = {
        device = diskDevice;
        type = "disk";
        content = {
          type = "gpt";
          partitions = {
            bios = {
              size = "1M";
              type = "EF02";
            };
            root = {
              size = "100%";
              content = {
                type = "btrfs";
                extraArgs = ["-L" "nixos" "-f"];
                subvolumes = btrfsSubvols;
              };
            };
          };
        };
      };
    })

    (lib.mkIf (bootLoader == "grub-uefi") {
      disko.devices.disk.main = {
        device = diskDevice;
        type = "disk";
        content = {
          type = "gpt";
          partitions = {
            ESP = {
              size = "256M";
              type = "EF00";
              content = {
                type = "filesystem";
                format = "vfat";
                mountpoint = "/boot";
              };
            };
            root = {
              size = "100%";
              content = {
                type = "btrfs";
                extraArgs = ["-L" "nixos" "-f"];
                subvolumes = btrfsSubvols;
              };
            };
          };
        };
      };
    })

    # == Raspberry Pi — disko: FAT32 /boot/firmware + btrfs root ==
    # (목적: RPi는 EFI 미지원으로 extlinux 사용, firmware 파티션 필수)
    (lib.mkIf isRpi {
      disko.devices.disk.main = {
        device = diskDevice;
        type = "disk";
        content = {
          type = "gpt";
          partitions = {
            firmware = {
              size = "512M";
              type = "EF00"; # FAT32 (RPi firmware/kernel/dtb)
              content = {
                type = "filesystem";
                format = "vfat";
                mountpoint = "/boot/firmware";
                mountOptions = ["fmask=0137" "dmask=0027"];
              };
            };
            root = {
              size = "100%";
              content = {
                type = "btrfs";
                extraArgs = ["-L" "nixos" "-f"];
                subvolumes = btrfsSubvols;
              };
            };
          };
        };
      };

      services.btrfs.autoScrub = {
        enable = true;
        interval = "weekly";
        fileSystems = ["/"];
      };
      services.fstrim.enable = true;
      environment.systemPackages = with pkgs; [btrfs-progs];
    })
  ];
})
