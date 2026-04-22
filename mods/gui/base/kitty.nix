{mkPartOf, ...}:
mkPartOf "mods.gui" (_: {
  hm = {
    programs.kitty.enable = true;

    # 폰트 설정 (pkgs에서 폰트 패키지를 가져오는 것이 좋습니다)
    programs.kitty = {
      font = {
        name = "NanumGothicCoding";
        size = 13.0;
      };

      # 상세 설정 (kitty.conf의 내용을 그대로 매핑)
      settings = {
        bold_font = "auto";
        italic_font = "auto";
        bold_italic_font = "auto";

        background_opacity = "0.95";
        window_padding_width = 0;
        confirm_os_window_close = -1;

        cursor_shape = "beam";
        shell_integration = "disabled";

        open_url_modifiers = "ctrl";
      };

      # 마우스 매핑 (extraConfig를 사용하거나 키워드 매핑이 필요할 수 있음)
      # kitty의 특수 매핑은 문자열 그대로 전달하는 것이 가장 확실합니다.
      keybindings = {
        # 스플릿/탭 닫기 시 확인창 (ignore-shell: 쉘만 있어도 물어봄)
        "ctrl+shift+w" = "close_window_with_confirmation ignore-shell";
        "ctrl+shift+q" = "close_tab_with_confirmation";
      };

      extraConfig = ''
        mouse_map middle release ungrabbed no_op
        mouse_map right press ungrabbed paste_from_clipboard
      '';
    };
  };
})
