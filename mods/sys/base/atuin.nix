{mkPartOf, ...}:
mkPartOf "mods.sys.base" (_: {
  hm = {
    programs.atuin = {
      enable = true;
      settings = {
        search = {
          filters = ["host" "directory"];
        };
        filter_mode = "host";
        filter_mode_shell_up_key_binding = "host";

        # 도움말을 켜야 검색창(프롬프트)이 안정적으로 보입니다.
        show_help = true;

        # 사용자가 요청한 최적 높이 12 (9번 항목까지 표시)
        inline_height = 12;

        # 검색 시에는 그래프를 숨깁니다.
        show_preview = false;

        style = "compact";
        invert = true;
        show_tabs = false;
        enter_accept = true;
        exit_mode = "return-query";
      };
    };
  };
})
