{mkModHere, ...}:
mkModHere __curPos "Cockpit Web Dashboard" (_: {
  os = {
    services.cockpit.enable = true;
    services.cockpit.port = 9090;
  };
})
