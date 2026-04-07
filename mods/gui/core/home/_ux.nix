{lib, ...}: {
  wayland.windowManager.hyprland.settings = {
    monitor = lib.mkDefault [",preferred,auto,1"];

    ### INPUT ###
    input = {
      kb_layout = "kr";
      kb_options = "korean:ralt_hangul,korean:rctrl_hanja";

      follow_mouse = 1;

      # 1. 마우스 기본 속도 (-1.0 ~ 1.0, 0이 기본값)
      sensitivity = lib.mkForce 1;

      # 2. 마우스 가속 프로필
      # "flat"으로 설정하면 가속이 꺼지고 일정한 속도로 움직입니다 (개발자분들이 선호함)
      # "adaptive"가 기본 가속 모드입니다.
      accel_profile = "adaptive";

      touchpad = {
        natural_scroll = true;
      };
    };

    # [OPTIONAL] 특정 하드웨어 전용 설정
    # device = [ { name = "epic-mouse-v1"; sensitivity = -0.5; } ];

    general = {
      resize_on_border = false;
      allow_tearing = false;
      layout = "dwindle";
    };

    dwindle = {
      pseudotile = true;
      preserve_split = true;
    };

    misc = {
      always_follow_on_dnd = true;
      focus_on_activate = true;
    };
  };

  wayland.windowManager.hyprland.settings.windowrulev2 = [
    # 모든 창을 기본적으로 플로팅
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

  # == Hide Clutter in Application Menu ==
  # (목적: 사용 빈도가 낮거나 배경에서 실행되는 도구들의 실행 아이콘을 숨겨 메뉴를 정리)
  xdg.desktopEntries = {
    "blueman-adapters" = {
      name = "Bluetooth Adapters (Hidden)";
      noDisplay = true;
    };
    "org.fcitx.Fcitx5" = {
      name = "Fcitx 5 (Hidden)";
      noDisplay = true;
    };
    "org.fcitx.fcitx5-migrator" = {
      name = "Fcitx 5 Migration Wizard (Hidden)";
      noDisplay = true;
    };
    "kbd-layout-viewer5" = {
      name = "Keyboard Layout Viewer (Hidden)";
      noDisplay = true;
    };
    "nixos-manual" = {
      name = "NixOS Manual (Hidden)";
      noDisplay = true;
    };
    "uuctl" = {
      name = "UWSM Control (Hidden)";
      noDisplay = true;
    };
  };
}
