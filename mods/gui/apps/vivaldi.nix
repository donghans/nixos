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
          # nixos-unstable 채널이 아직 nixpkgs#547639 (버전 스킴 변경)을 반영하지 않아
          # vivaldi 8.1.4087.58과 ffmpeg 심볼 불일치(av_dynamic_hdr_smpte2094_app5_to_t35)로
          # 크래시함. 같은 snap 안의 최신 서브폴더를 직접 가리키도록 임시 override.
          # 채널이 따라잡으면 (nixpkgs 커밋 377e73e 이후) 이 override는 제거해도 됨.
          vivaldi-ffmpeg-codecs = unstable.vivaldi-ffmpeg-codecs.overrideAttrs (old: {
            version = "0-unstable-2026-05-18";
            installPhase = ''
              install -vD chromium-ffmpeg-git-2026-05-18/chromium-ffmpeg/libffmpeg.so $out/lib/libffmpeg.so
            '';
          });
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
