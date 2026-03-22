{ config, ... }: {
  imports = [
    # ./hardware/$HOST_ID.nix
    ./base/developer.nix
  ];

  fileSystems."/boot" =
    { device = "/dev/disk/by-label/boot";
      fsType = "vfat";
      options = [ "fmask=0022" "dmask=0022" ];
    };

  services = {
    auto-cpufreq = {
      enable = true;

      settings.charger = {
        governor = "performance";
        turbo = "always";
      };
    };

    irqbalance.enable = true;
  };
}
