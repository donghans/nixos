{isNixOS ? false, ...}: {
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

  config = {
    mods.sys.fonts.enable = true;
    mods.sys.vfs.enable = true;
  };
}
