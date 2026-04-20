{mkModHere, ...}:
mkModHere __curPos "Slack" ({
  pkgs,
  unstable,
  ...
}: {
  hm = {
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
})
