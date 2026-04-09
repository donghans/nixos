{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.headscale;
in {
  options.mods.sys.services.headscale.enable = mkEnableOption "Headscale (Tailscale Control Server)";

  config = mkIf cfg.enable (
    if isNixOS
    then {
      services.headscale.enable = true;
      services.headscale.settings.dns.base_domain = "server.local";
    }
    else {}
  );
}
