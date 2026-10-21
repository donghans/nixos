{mkModOf, ...}:
mkModOf "mods.gui" __curPos "Vivaldi Browser" ({
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
          # 디버깅 포트는 127.0.0.1 에만 열린다(웹 페이지의 WebSocket 접근은 크로미움이 막음). observe-browser 가 폭주 시 탭별 CPU 를 읽기 전용으로 잰다.
          # 같은 PC 의 다른 프로그램도 접근할 수 있으므로 필요 없어지면 이 인자를 지운다.
          commandLineArgs = ["--lang=ko" "--remote-debugging-port=9222"];
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
