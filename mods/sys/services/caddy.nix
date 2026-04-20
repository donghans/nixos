{mkMod, ...}:
mkMod __curPos "Caddy Web Server with reverse proxy support" ({
  cfg,
  lib,
  ...
}: {
  options = {
    configText = lib.mkOption {
      type = lib.types.lines;
      default = "";
      description = "Extra Caddyfile configuration";
    };
  };
  os = {
    services.caddy = {
      enable = true;
      extraConfig = cfg.configText;
    };
    networking.firewall.allowedTCPPorts = [80 443];
  };
})
