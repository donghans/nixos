{mkModHere, ...}:
mkModHere __curPos "Vivaldi Browser" ({
  pkgs,
  unstable,
  ...
}: let
  # Chromium distribution 설정만 유효 (Vivaldi 전용 설정은 initial_preferences로 제어 불가)
  initialPreferences = builtins.toJSON {
    distribution = {
      skip_first_run_ui = true;
      show_welcome_page = false;
      import_bookmarks = false;
      import_history = false;
    };
  };
in {
  hm = {
    home.packages = [
      ((unstable.vivaldi.override {
          proprietaryCodecs = true;
          inherit (unstable) vivaldi-ffmpeg-codecs;
          commandLineArgs = ["--lang=ko"];
        }).overrideAttrs (old: {
          postInstall =
            (old.postInstall or "")
            + ''
              cp ${pkgs.writeText "initial_preferences" initialPreferences} $out/opt/vivaldi/initial_preferences
            '';
        }))
    ];
  };
})
