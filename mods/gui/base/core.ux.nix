# 인터랙션 설정: 입력, 레이아웃, 윈도우 룰, 앱 메뉴 정리
{mkPartOf, ...}:
mkPartOf "mods.gui" ({lib, ...}: {
  hm = {
    wayland.windowManager.hyprland.settings = {
      monitor = lib.mkDefault [",preferred,auto,1"];

      ### INPUT ###
      input = {
        kb_layout = "kr";
        kb_options = "korean:ralt_hangul,korean:rctrl_hanja";
        resolve_binds_by_sym = true;

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
        preserve_split = true;
      };

      misc = {
        always_follow_on_dnd = true;
        focus_on_activate = true;
      };
    };

    wayland.windowManager.hyprland.extraConfig = ''
      -- 모든 창을 기본적으로 플로팅
      hl.window_rule({ match = { class = ".*" }, float = true })

      hl.window_rule({
        match = { class = "^$", title = "^$", xwayland = true, float = true, fullscreen = false, pin = false },
        no_initial_focus = true
      })

      -- Authentication Prompts (Gnome Keyring, Polkit)
      hl.window_rule({
        match = { class = "^(gcr-prompter)$" },
        float = true,
        dim_around = true,
        center = true,
        stay_focused = true,
        pin = true
      })

      hl.window_rule({
        match = { class = "^(org.gnome.PolkitAgent1.*)$" },
        float = true,
        dim_around = true,
        center = true,
        stay_focused = true
      })

      hl.window_rule({
        match = { class = "hyprland-run" },
        float = true,
        move = "20 100%-120"
      })

      -- 1. JetBrains의 모든 팝업(툴팁, 자동완성)에 대해 애니메이션 끄기 (깜빡임의 주원인)
      hl.window_rule({
        match = { class = "^(jetbrains-.*)$", title = "^(win.*)$" },
        no_anim = true
      })

      -- 2. 팝업이 포커스를 뺏지 않도록 설정하되, '내용'은 볼 수 있게 함
      hl.window_rule({
        match = { class = "^(jetbrains-.*)$", title = "^(win.*)$" },
        no_initial_focus = true
      })
      hl.window_rule({
        match = { class = "^(jetbrains-.*)$", title = "^(?!win.*)$" },
        stay_focused = true
      })

      -- 3. XWayland에서의 부동 소수점 반올림 문제 해결 (간혹 도움이 됨)
      hl.window_rule({
        match = { class = "^(jetbrains-.*)$", title = "^(win.*)$" },
        rounding = 0
      })
    '';

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
  };
})
