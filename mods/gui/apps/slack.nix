{
  config,
  lib,
  pkgs,
  unstable,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.gui.apps.slack;
in
  {options.mods.gui.apps.slack.enable = mkEnableOption "Slack";}
  // (
    if isNixOS
    then {}
    else {
      config = mkIf cfg.enable {
        home.packages = [
          (pkgs.symlinkJoin {
            name = "slack";
            paths = [unstable.slack];
            buildInputs = [pkgs.makeWrapper];
            postBuild = ''
              wrapProgram $out/bin/slack \
                --add-flags "--enable-wayland-ime=false"
            '';
          })
        ];
        xdg.mimeApps.defaultApplications = {
          "x-scheme-handler/slack" = ["slack.desktop"];
        };
      };
    }
  )
