{mkMod, ...}:
mkMod __curPos "Bitwarden" ({pkgs, ...}: {
  hm = {
    home.packages = with pkgs; [bitwarden-desktop bitwarden-cli];
  };
})
