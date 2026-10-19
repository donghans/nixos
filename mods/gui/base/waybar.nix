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
          # 가상 키보드 버튼은 2-in-1 호스트만, 배터리는 모든 노트북
          lib.optionals config.workspace.convertible ["custom/vkbsize" "custom/vkbmode" "custom/vkb"]
          ++ lib.optionals (config.workspace.type == "laptop") ["battery"]
        )
        ++ ["clock"];

      # 터치로 누를 수 있는 버튼들(터치스크린에는 우클릭/스크롤이 없어서 모두 단일 탭으로 동작)
      #  ⌨: 가상 키보드 접기/펴기 / ⧉: 하단 고정↔플로팅 / 크기(S·M·L): 탭하면 다음 크기. 크기·⧉ 는 키보드가 보일 때만 나타남
      #  세 버튼 모두 노트북 모드에서는 키보드가 떠 있을 때만 보이고 텐트/태블릿에서는 항상 보임(vkb waybar 가 빈 출력을 내면 모듈이 사라짐)
      # (vkb 가 상태를 바꾸거나 사용 모드가 바뀔 때만 waybar 에 신호(RTMIN+8)를 보내 다시 그리므로 폴링이 없음. 한/영 전환은 시스템 트레이의 fcitx5 아이콘과 키보드 안의 한/영 키)
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
      "custom/vkbmode" = {
        exec = "vkb waybar mode";
        return-type = "json";
        interval = "once";
        signal = 8;
        on-click = "vkb mode toggle";
        tooltip = true;
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
