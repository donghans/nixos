{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  pkgs,
  config,
  lib,
  ...
}: {
  hm = {
    # waybar 세션 시작
    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 900 [
      "uwsm app -- sh -c 'sleep 2 && ${pkgs.waybar}/bin/waybar'"
    ];

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
      spacing = 0;

      modules-left = ["hyprland/workspaces" "hyprland/submap"];
      modules-center = ["hyprland/window"];
      modules-right =
        ["tray"]
        ++ (
          if config.workspace.type == "laptop"
          then ["custom/vkbsize" "custom/vkb" "custom/ime" "battery"]
          else []
        )
        ++ ["clock"];

      # 터치로 누를 수 있는 버튼들(터치스크린에는 우클릭/스크롤이 없어서 모두 단일 탭으로 동작)
      #  ⌨: 가상 키보드 접기/펴기 / 크기(S·M·L): 키보드가 보일 때만 나타나고 탭하면 다음 크기 / 한·A: fcitx5 한/영 전환
      # (vkb 가 상태를 바꿀 때만 waybar 에 신호(RTMIN+8)를 보내 다시 그리므로 폴링이 없음. 한/영 표시는 2초마다 확인)
      "custom/vkb" = {
        exec = "vkb waybar";
        return-type = "json";
        interval = "once";
        signal = 8;
        on-click = "vkb toggle";
        tooltip = true;
      };
      "custom/vkbsize" = {
        exec = "vkb waybar size";
        return-type = "json";
        interval = "once";
        signal = 8;
        on-click = "vkb size cycle";
        tooltip = true;
      };
      "custom/ime" = {
        exec = "case \"$(fcitx5-remote -n)\" in hangul) echo 한 ;; *) echo A ;; esac";
        interval = 2;
        on-click = "fcitx5-remote -t";
        tooltip = false;
      };

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
        icon-size = 18;
        spacing = 4;
      };

      "clock" = {
        format = "{:%Y-%m-%d %H:%M}";
        tooltip-format = "{:%A, %B %d, %Y}";
      };
    };

    programs.waybar.style = builtins.readFile ../../_data/waybar/style.css;
  };
})
