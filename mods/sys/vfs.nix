{mkMod, ...}:
mkMod __curPos "Virtual File Systems (GVFS, Udisks2)" (_: {
  os = {
    services.gvfs.enable = true;
    services.udisks2.enable = true;
  };
  # (USB 자동 마운트는 mods/gui/utils/thunar.nix 의 thunar-volman 이 담당)
})
