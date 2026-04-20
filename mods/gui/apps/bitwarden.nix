{mkModOf, ...}:
mkModOf "mods.gui" __curPos "Bitwarden" ({pkgs, ...}: {
  hm = {
    home.packages = with pkgs; [bitwarden-desktop bitwarden-cli];
  };
})
