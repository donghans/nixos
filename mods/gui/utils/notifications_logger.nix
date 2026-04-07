{
  config,
  lib,
  ...
}:
with lib; let
  cfg = config.mods.gui.utils.notifications_logger;
in {
  imports = [./custom-notify-logger-module.nix];
  options.mods.gui.utils.notifications_logger.enable = mkEnableOption "Custom Notification Logger";
  config = mkIf cfg.enable {
    services.custom-notify-logger.enable = true;
  };
}
