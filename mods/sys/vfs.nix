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
      home.packages = with pkgs; [trash-cli];
      # aliases could be moved here if they exist
    }
  );
}
