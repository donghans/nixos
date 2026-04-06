{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.tailscale;
in
  if isNixOS
  then {
    config = mkIf cfg.enable {
      services.tailscale.enable = true;
    };
  }
  else {}
