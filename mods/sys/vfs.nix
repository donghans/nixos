{mkMod, ...}:
mkMod __curPos "Virtual File Systems (GVFS, Udisks2)" (_: {
  os = {
    services.gvfs.enable = true;
    services.udisks2.enable = true;
  };
  hm = {
    services.udiskie.enable = true; # (목적: USB 자동 마운트 및 트레이 알림)
  };
})
