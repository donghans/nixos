{mkModHere, ...}:
mkModHere __curPos "SpeedCrunch" ({pkgs, ...}: {
  hm = {
    home.packages = [pkgs.speedcrunch];
  };
})
