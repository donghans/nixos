{mkModOf, ...}:
mkModOf "mods.gui" __curPos "SpeedCrunch" ({pkgs, ...}: {
  hm = {
    home.packages = [pkgs.speedcrunch];
  };
})
