_: {
  programs.atuin = {
    enable = true;
    settings = {
      search = {
        filters = ["host" "directory"];
      };
      filter_mode = "host";
      filter_mode_shell_up_key_binding = "host";
      style = "compact";
      inline_height = 30;
      max_preview_height = 20;
      invert = true;
      show_tabs = false;
      enter_accept = true;
      exit_mode = "return-query";
    };
  };
}
