{ pkgs, ... }: {
  wayland.windowManager.hyprland.enable = true;

  wayland.windowManager.hyprland.settings = {
    "$mainMod" = "SUPER";

    ### INPUT ###
    input = {
      kb_layout = "kr";
      kb_options = "korean:ralt_hangul,korean:rctrl_hanja";

      follow_mouse = 1;
      sensitivity = 0;
      touchpad = {
        natural_scroll = true;
      };
    };

    device = [
      {
        name = "epic-mouse-v1";
        sensitivity = -0.5;
      }
    ];

    ### WINDOWS AND WORKSPACES ###
    windowrulev2 = [
      "float, class:.*"

      "nofocus, class:^$, title:^$, xwayland:1, floating:1, fullscreen:0, pinned:0"

      # Authentication Prompts (Gnome Keyring, Polkit)
      "float, class:^(gcr-prompter)$"
      "dimaround, class:^(gcr-prompter)$"
      "center, class:^(gcr-prompter)$"
      "stayfocused, class:^(gcr-prompter)$"
      "pin, class:^(gcr-prompter)$"

      "float, class:^(org.gnome.PolkitAgent1.*)$"
      "dimaround, class:^(org.gnome.PolkitAgent1.*)$"
      "center, class:^(org.gnome.PolkitAgent1.*)$"
      "stayfocused, class:^(org.gnome.PolkitAgent1.*)$"

      "float, class:hyprland-run"
      "move 20 100%-120, class:hyprland-run"

      # 1. JetBrains의 모든 팝업(툴팁, 자동완성)에 대해 애니메이션 끄기 (깜빡임의 주원인)
      "noanim, class:^(jetbrains-.*)$, title:^(win.*)$"

      # 2. 팝업이 포커스를 뺏지 않도록 설정하되, '내용'은 볼 수 있게 함
      "noinitialfocus, class:^(jetbrains-.*)$, title:^(win.*)$"
      "stayfocused, class:^(jetbrains-.*)$, title:^(?!win.*)$"

      # 3. XWayland에서의 부동 소수점 반올림 문제 해결 (간혹 도움이 됨)
      "rounding 0, class:^(jetbrains-.*)$, title:^(win.*)$"
    ];
  };

  services.hypridle.enable = true; # 보안: 자리를 비우면 화면 잠금 준비 (hypridle)
}
