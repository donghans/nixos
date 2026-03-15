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

      "float, class:hyprland-run"
      "move 20 100%-120, class:hyprland-run"
    ];
  };

  services.hypridle.enable = true; # 보안: 자리를 비우면 화면 잠금 준비 (hypridle)
}
