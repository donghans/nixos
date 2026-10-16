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

    # 오디오 장치/음량 조절 화면 (waybar 오디오 모듈을 클릭하면 열림)
    home.packages = [pkgs.pavucontrol];

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
        ["tray" "pulseaudio"]
        ++ (
          if config.workspace.type == "laptop"
          then ["battery"]
          else []
        )
        ++ ["clock"];

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

      # 현재 출력 음량 + 마이크 상태. 클릭: 오디오 설정(장치 선택), 우클릭: 출력 음소거, 가운데 클릭: 마이크 음소거,
      # 스크롤: 음량. (아이콘 폰트 의존을 피하려고 텍스트로 표시 — 배터리 모듈과 같은 방식)
      "pulseaudio" = {
        format = "VOL {volume}%  {format_source}";
        format-muted = "MUTE  {format_source}";
        format-source = "MIC {volume}%";
        format-source-muted = "MIC OFF";
        scroll-step = 5;
        on-click = "${pkgs.pavucontrol}/bin/pavucontrol";
        on-click-right = "${pkgs.wireplumber}/bin/wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle";
        on-click-middle = "${pkgs.wireplumber}/bin/wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle";
        tooltip-format = "{desc}\n입력: {source_desc}";
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
