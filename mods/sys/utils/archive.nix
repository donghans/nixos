{mkMod, ...}:
mkMod __curPos "Archive tools (zip, 7z)" ({pkgs, ...}: {
  os.environment.systemPackages = with pkgs; [zip unzip p7zip];
  hm.home.packages = with pkgs; [zip unzip p7zip];
})
