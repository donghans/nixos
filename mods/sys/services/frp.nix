{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.frp;
in {
  options.mods.sys.services.frp.enable = mkEnableOption "Fast Reverse Proxy (FRP)";

  config = mkIf cfg.enable (
    if isNixOS
    then {
      services.frp.enable = true;
      services.frp.role = "client";
    }
    else {}
  );
}
