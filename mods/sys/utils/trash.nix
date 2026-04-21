{mkMod, ...}:
mkMod __curPos "Trash CLI (safe delete)" ({pkgs, ...}: {
  hm = {
    home.packages = with pkgs; [trash-cli];

    home.shellAliases = {
      tmv = "trash-put";
      tls = "trash-list";
      trm = "trash-empty";
      trs = "trash-restore";
    };
  };
})
