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

    "tray" = {
      icon-size = 16;
      spacing = 12;
    };

    "clock" = {
      format = "   {:%Y-%m-%d %H:%M}   ";
      tooltip-format = "{:%A, %B %d, %Y}";
    };
  };

  programs.waybar.style = ''
    /* Waybar 전체 배경 */
    window#waybar {
      background-color: rgba(0, 0, 0, 0.5);
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
  '';
}
