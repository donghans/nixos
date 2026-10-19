{mkModOf, ...}:
mkModOf "mods.gui" __curPos "GIMP" ({pkgs, ...}: {
  hm = {
    home.packages = [pkgs.gimp];
  };
})
