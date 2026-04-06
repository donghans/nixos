{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.vfs;
in {
  config = mkIf cfg.enable (
    if isNixOS
    then {
      services.gvfs.enable = true;
      services.udisks2.enable = true;
    }
    else {
      services.udiskie.enable = true; # (목적: USB 자동 마운트 및 트레이 알림)

      home.packages = with pkgs; [trash-cli];

      home.shellAliases = {
        tp = "trash-put";
        tl = "trash-list";
        tr = "trash-restore";
        te = "trash-empty";
      };
    }
  );
}
