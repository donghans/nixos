{mkMod, ...}:
mkMod __curPos "Fast Reverse Proxy (FRP)" (_: {
  os = {
    services.frp.enable = true;
    services.frp.role = "client";
  };
})
