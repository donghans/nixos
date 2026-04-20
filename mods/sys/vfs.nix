{mkModHere, ...}:
mkModHere __curPos "Virtual File Systems (GVFS, Udisks2, trash-cli)" ({pkgs, ...}: {
  os = {
    services.gvfs.enable = true;
    services.udisks2.enable = true;
  };
  hm = {
    services.udiskie.enable = true; # (목적: USB 자동 마운트 및 트레이 알림)

    home.packages = with pkgs; [trash-cli];

    home.shellAliases = {
      tmv = "trash-put";
      tls = "trash-list";
      trm = "trash-empty";
      trs = "trash-restore";
    };
  };
})
