{
  config,
  lib,
  unstable,
  isNixOS ? false,
  ...
}:
if isNixOS
then {}
else
  with lib; let
    cfg = config.mods.gui.apps.slack;
  in {
    config = mkIf cfg.enable {
      home.packages = [unstable.slack];
      xdg.mimeApps.defaultApplications = {
        "x-scheme-handler/slack" = ["slack.desktop"];
      };
    };
  }
