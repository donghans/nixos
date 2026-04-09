_: {
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
      confirm_os_window_close = 0;

      cursor_shape = "beam";
      shell_integration = "disabled";
    };

    # 마우스 및 키 매핑
    extraConfig = ''
      mouse_map middle release ungrabbed no_op
      mouse_map right press ungrabbed paste_from_clipboard

      # == Home/End Key Compatibility Fix ==
      # (목적: Node.js/Gemini CLI 등에서 Home/End가 기호로 출력되는 문제 해결)
      map home send_text all \x1b[H
      map end send_text all \x1b[F
    '';
  };
}
