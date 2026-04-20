{
  lib,
  config,
  ...
}: {
  options.mods.gui.enable = lib.mkEnableOption "GUI Bundle (Hyprland, Waybar, etc)";

  # (cross-domain: gui.enable → sys.fonts + sys.vfs 자동 활성화)
  # gui/apps + gui/utils 모듈은 mkModOf "mods.gui"로 자동 cascade됨
  config = lib.mkIf config.mods.gui.enable {
    mods.sys.fonts.enable = true;
    mods.sys.vfs.enable = true;
  };
}
