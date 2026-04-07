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
