{mkPartOf, ...}:
mkPartOf "mods.sys.base" ({
  pkgs,
  config,
  lib,
  ...
}: let
  inherit (config.workspace) bootLoader;
  inherit (config.workspace) diskDevice;

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
    # == 로컬 호스트 (bootLoader="systemd-boot") — 수동 fileSystems 선언 ==
    (lib.mkIf (bootLoader == "systemd-boot") {
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
  ];
})
