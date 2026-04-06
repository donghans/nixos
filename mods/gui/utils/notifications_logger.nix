{
  config,
  lib,
  ...
}:
with lib; let
  cfg = config.mods.gui.utils.notifications_logger;
in {
  imports = [./custom-notify-logger-module.nix];
  config = mkIf cfg.enable {
    services.custom-notify-logger.enable = true;
  };
}
