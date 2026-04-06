{
  lib,
  config,
  isNixOS ? false,
  ...
}:
with lib; {
  imports =
    [
      ./apps/vivaldi.nix
      ./apps/slack.nix
      ./apps/bitwarden.nix
      ./utils/notifications_logger.nix
    ]
    ++ (
      if isNixOS
      then [./core/os.nix]
      else []
    )
    ++ (
      if !isNixOS
      then [./core/home.nix]
      else []
    );

  config = mkIf config.mods.gui.enable {
    mods.sys.fonts.enable = true;
    mods.sys.vfs.enable = true;
  };
}
