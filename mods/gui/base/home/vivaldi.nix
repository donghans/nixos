# [working-refactor] 해당 구문은 before-refactor/lib/_base/hyprland.home/vivaldi.nix 에 있었음
# [working-refactor] 해당 구문은 after-refactor/... 로 들어가야 함
{unstable, ...}: {
  home.packages = [
    ((unstable.vivaldi.override {
        proprietaryCodecs = true;
        inherit (unstable) vivaldi-ffmpeg-codecs;
        commandLineArgs = ["--lang=ko"];
      }).overrideAttrs (old: {
        postInstall =
          (old.postInstall or "")
          + ''
            # 초기 설정 스킵 및 다크 테마, 좌측 탭 설정
            cat <<EOF > $out/opt/vivaldi/initial-config.json
            {
              "preferences": {
                "vivaldi": {
                  "welcome_page_shown": true,
                  "tabs": { "bar_position": 2 },
                  "themes": { "current": "Vivaldi Dark" }
                }
              }
            }
            EOF

            # Chromium 기반 초기 설정 UI 스킵
            cat <<EOF > $out/opt/vivaldi/initial_preferences
            {
              "distribution": {
                "skip_first_run_ui": true,
                "show_welcome_page": false,
                "import_bookmarks": false,
                "import_history": false
              }
            }
            EOF
          '';
      }))
  ];
}
