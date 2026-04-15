{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.incus;
in {
  options.mods.sys.services.incus.enable = mkEnableOption "Incus hypervisor";

  config = mkIf cfg.enable (
    if isNixOS
    then {
      virtualisation.incus.enable = true;
      virtualisation.incus.ui.enable = true;
      networking.firewall.allowedTCPPorts = [8443];
      networking.nftables.enable = true;
      users.users.${config.workspace.username}.extraGroups = ["incus-admin"];

      virtualisation.incus.preseed = {
        networks = [
          {
            name = "incusbr0";
            type = "bridge";
            config = {
              "ipv4.address" = "auto";
              "ipv6.address" = "auto";
              "ipv4.nat" = "true";
              "ipv6.nat" = "true";
            };
          }
        ];
        storage_pools = [
          {
            name = "default";
            driver = "btrfs"; # 이 프로젝트가 Btrfs 기반이므로 btrfs 권장
            config = {
              source = "/var/lib/incus/storage-pools/default";
            };
          }
        ];
        profiles = [
          {
            name = "default";
            devices = {
              eth0 = {
                name = "eth0";
                network = "incusbr0";
                type = "nic";
              };
              root = {
                path = "/";
                pool = "default";
                type = "disk";
              };
            };
          }
          {
            name = "win11";
            config = {
              "limits.cpu" = "4";
              "limits.memory" = "8GiB";
              "raw.qemu" = "-device usb-tablet";
              "security.secureboot" = "true";
            };
            devices = {
              eth0 = {
                name = "eth0";
                network = "incusbr0";
                type = "nic";
              };
              root = {
                path = "/";
                pool = "default";
                type = "disk";
                "io.bus" = "nvme";
                size = "64GiB";
              };
              vtpm = {
                type = "tpm";
              };
            };
          }
        ];
      };
    }
    else {}
  );
}
