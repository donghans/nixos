{ pkgs, ... }: {
  programs.hyprlock.enable = true;

  programs.hyprlock.settings = {
    general = {
      no_fade_in = false;
      grace = 0;
      disable_loading = true;
      hide_cursor = true;
    };

    background = [
      {
        path = "screenshot";
        blur_passes = 2; # 미니멀한 느낌을 위해 블러를 조금 더 높였습니다.
        blur_size = 4;
      }
    ];

    input-field = [
      {
        monitor = "";
        size = "512, 64";
        outline_thickness = 0; # 박스 테두리 제거
        dots_size = 0.33; # 점 크기 살짝 조절
        dots_spacing = 0.33; # 점 사이 간격 확보
        dots_center = true;

        # 배경과 테두리를 완전히 투명하게 설정
        outer_color = "rgba(0, 0, 0, 0)";
        inner_color = "rgba(0, 0, 0, 0)";
        font_color = "rgb(200, 200, 200)"; # 점(문자)의 색상

        fade_on_empty = false; # 입력 안 할 때도 위치를 알 수 있게 유지 (선택사항)
        placeholder_text = ""; # 텍스트 없이 깔끔하게
        hide_input = false;
        position = "0, 0";
        halign = "center";
        valign = "center";

        # 검증 중일 때도 투명 유지
        check_color = "rgba(0, 0, 0, 0.25)";

        # 실패 시 설정
        fail_color = "rgba(200, 0, 0, 0.25)"; # 실패 시에도 박스 색상은 투명하게 유지
        fail_text = "";
      }
    ];
  };

  # 아이들 기본 세팅
  services.hypridle.enable = true;
  services.hypridle.settings.general.lock_cmd = "pidof hyprlock || hyprlock"; # 잠금 명령
}
