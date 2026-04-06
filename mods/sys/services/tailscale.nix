{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.tailscale;
in {
  config = mkIf (cfg.enable && isNixOS) {
    services.tailscale.enable = true;
  };
}
