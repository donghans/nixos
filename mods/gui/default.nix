{
  lib,
  config,
  ...
}:
with lib; {
  imports = [
    ./core
    ./apps/vivaldi.nix
    ./apps/slack.nix
    ./apps/bitwarden.nix
    ./utils/notifications_logger.nix
  ];

  config = mkIf config.mods.gui.enable {
    mods.sys.fonts.enable = true;
    mods.sys.vfs.enable = true;
  };
}
