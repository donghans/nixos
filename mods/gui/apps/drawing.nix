{mkModOf, ...}:
mkModOf "mods.gui" __curPos "Drawing" ({pkgs, ...}: {
  hm = {
    home.packages = [pkgs.drawing];
  };
})
