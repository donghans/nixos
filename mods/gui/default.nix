{
  lib,
  config,
  ...
}:
with lib; let
  inherit (import ../_lib.nix {inherit lib;}) importDir;
in {
  imports =
    [./core]
    ++ importDir ./apps
    ++ importDir ./utils;

  options.mods.gui.enable = mkEnableOption "GUI Bundle (Hyprland, Waybar, etc)";

  # == gui.enable 마스터 스위치: 하위 항목 기본값 활성화 ==
  # (사용자는 개별 항목을 `lib.mkForce false`로 비활성화 가능)
  config = mkIf config.mods.gui.enable {
    mods.sys.fonts.enable = true;
    mods.sys.vfs.enable = true;
    mods.gui.apps.vivaldi.enable = mkDefault true;
    mods.gui.apps.slack.enable = mkDefault true;
    mods.gui.apps.bitwarden.enable = mkDefault true;
    mods.gui.utils.custom-notify-logger.enable = mkDefault true;
  };
}
