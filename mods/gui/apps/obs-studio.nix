{mkModOf, ...}:
mkModOf "mods.gui" __curPos "OBS Studio" ({pkgs, ...}: {
  hm = {
    home.packages = [pkgs.obs-studio];
  };
})
