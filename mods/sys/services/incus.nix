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
    }
    else {}
  );
}
