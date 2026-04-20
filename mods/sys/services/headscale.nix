{mkMod, ...}:
mkMod __curPos "Headscale (Tailscale Control Server)" (_: {
  os = {
    services.headscale.enable = true;
    services.headscale.settings.dns.base_domain = "server.local";
  };
})
