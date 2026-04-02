{ pkgs, metaConfig, ... }: {
  programs.waybar.enable = true;

  # waybar/config 내용
  programs.waybar.settings.mainBar = {
    layer = "top";
    position = "top";
    height = 24;

    margin-top = 0;
    margin-bottom = 0;
    margin-left = 0;
    margin-right = 0;

    modules-left = [ "hyprland/workspaces" "hyprland/submap" ];
    modules-center = [ "hyprland/window" ];
    modules-right = [ "tray" ]
    ++ (if metaConfig.isLaptop then [ "battery" ] else [ ])
    ++ [ "clock" ];

    "hyprland/workspaces" = {
      format = "{name}";
      on-click = "activate";
      all-outputs = false;
      sort-by-number = true;
    };

    "hyprland/window" = {
      format = "{}";
      separate-outputs = true;
    };

    "battery" = {
      format = "{} %";
      states = {
        warning = 30;
        critical = 15;
      };
    };

    "tray" = {
      icon-size = 16;
      spacing = 6;
    };

    "clock" = {
      format = "{:%Y-%m-%d %H:%M}  ";
      tooltip-format = "{:%A, %B %d, %Y}";
    };
  };

  programs.waybar.style = ''
    /* Waybar 전체 배경 */
    window#waybar {
      background-color: rgba(0, 0, 0, 0.75);
      border-bottom: none;
    }

    /* 워크스페이스 버튼 공통 설정 */
    #workspaces button {
      padding: 0 4px;
      margin: 0;
      background: transparent;  /* 평상시 배경 투명 */
      color: #ffffff;
      border: none;
      border-radius: 0;         /* 각진 형태 */
      box-shadow: none;
      transition: all 0.1s ease;
    }

    /* 1. 일반 버튼에 마우스를 올렸을 때 (Hover) */
    #workspaces button:hover {
      background-color: rgba(51, 204, 255, 1);
      color: #000000;
    }

    /* 2. 현재 활성화된 버튼 (Active) */
    #workspaces button.active {
      color: #33ccff;
      background-color: transparent; /* 활성 상태여도 마우스 안 올리면 배경 투명 */
      box-shadow: inset 0 -3px 0 #33ccff; /* 하단 선으로만 표시 */
    }

    /* 3. 활성화된 버튼에 마우스를 올렸을 때 (Active Hover) */
    #workspaces button.active:hover {
      background-color: rgba(51, 204, 255, 1);
      color: #000000;
    }

    /* 워크스페이스에 창이 있을 때 (점유 중) */
    #workspaces button.occupied {
      color: #bbbbbb;
    }

    /* 긴급 상황 */
    #workspaces button.urgent {
      background-color: #ebcb8b;
      color: #2e3440;
    }

    /* Tray 오른쪽 패딩 추가 */
    #tray {
      padding-right: 4px; /* 원하는 간격만큼 조절하세요 */
    }

    #battery {
      padding: 0 1px;
      margin: 0 3px;
    }

    /* 충전 중일 때(charging) active 워크스페이스와 같은 밑줄 효과 */
    #battery.charging, #battery.plugged {
      color: #33ccff; /* 글자색도 active와 맞추면 더 깔끔합니다 */
      box-shadow: inset 0 -3px 0 #33ccff; /* 하단 3px 선 */
    }

    /* 배터리 경고 시 스타일 */
    #battery.warning:not(.charging) {
      color: #ebcb8b;
      box-shadow: inset 0 -3px 0 #ebcb8b; /* 경고는 노란 밑줄 */
    }

    /* 배터리 심각 시 스타일 */
    #battery.critical:not(.charging) {
      color: #f38ba8;
      box-shadow: inset 0 -3px 0 #f38ba8; /* 심각은 빨간 밑줄 */
    }

    #clock {
      padding: 0 4px;
    }
  '';
}
