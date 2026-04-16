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
        config = {
          "core.https_address" = ":8443";
        };
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
            driver = "btrfs";
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
        ];
      };
    }
    else {}
  );
}
