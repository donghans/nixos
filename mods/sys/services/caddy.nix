{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.caddy;
in {
  options.mods.sys.services.caddy = {
    enable = mkEnableOption "Caddy Web Server with reverse proxy support";
    configText = mkOption {
      type = types.lines;
      default = "";
      description = "Extra Caddyfile configuration";
    };
  };

  config = mkIf cfg.enable (
    if isNixOS
    then {
      services.caddy = {
        enable = true;
        extraConfig = cfg.configText;
      };
      networking.firewall.allowedTCPPorts = [80 443];
    }
    else {}
  );
}
