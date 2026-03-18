{ pkgs, ... }: let
  # 모니터 스왑 스크립트 정의
  swapMonitors = pkgs.writeShellScriptBin "hypr-swap-monitors" ''
    # jq로 현재 포커스된 모니터와 첫 번째 비포커스 모니터를 명확히 추출
    MONITORS_JSON=$(hyprctl monitors -j)
    FOCUSED=$(echo "$MONITORS_JSON" | ${pkgs.jq}/bin/jq -r '.[] | select(.focused == true) | .name')
    TARGET=$(echo "$MONITORS_JSON" | ${pkgs.jq}/bin/jq -r '.[] | select(.focused == false) | .name' | head -n 1)

    # dispatch 명령어 실행
    if [ -n "$FOCUSED" ] && [ -n "$TARGET" ]; then hyprctl dispatch swapactiveworkspaces "$FOCUSED" "$TARGET"; fi
  '';

  # 사용되는 명령어의 파일 경로 정의
  grim = "${pkgs.grim}/bin/grim";
  slurp = "${pkgs.slurp}/bin/slurp";
  swappy = "${pkgs.swappy}/bin/swappy";
  cliphist = "${pkgs.cliphist}/bin/cliphist";
  fuzzel = "${pkgs.fuzzel}/bin/fuzzel";
  wl-copy = "${pkgs.wl-clipboard}/bin/wl-copy";
in {
  wayland.windowManager.hyprland.settings = {
    bind = [
      "$mainMod, Q, killactive,"
      "$mainMod SHIFT, Q, exec, command -v hyprshutdown >/dev/null 2>&1 && hyprshutdown || hyprctl dispatch exit"
      "$mainMod, F, togglefloating,"
      "$mainMod, P, exec, ${fuzzel}"
      "$mainMod, V, exec, ${cliphist} list | ${fuzzel} --dmenu | ${cliphist} decode | ${wl-copy}"
      "$mainMod, N, exec, cat -s ~/.local/share/notify_logs/history.log* | tac | ${fuzzel} --dmenu --width 150 --placeholder \"Search 30-day History...\""
      "$mainMod, L, exec, hyprlock"

      # Special workspace
      "$mainMod, S, togglespecialworkspace, magic"
      "$mainMod SHIFT, S, movetoworkspace, special:magic"

      # Scroll through existing workspaces with mainMod + scroll
      "$mainMod, mouse_down, workspace, r-1"
      "$mainMod, mouse_up, workspace, r+1"
      "$mainMod SHIFT, mouse_down, movetoworkspace, r-1"
      "$mainMod SHIFT, mouse_up, movetoworkspace, r+1"
      "$mainMod SHIFT CTRL, mouse_down, movetoworkspacesilent, r-1"
      "$mainMod SHIFT CTRL, mouse_up, movetoworkspacesilent, r+1"

      # Swap workspaces (active monitor <=> latest inactive monitor)
      "$mainMod SHIFT, mouse:274, exec, ${swapMonitors}/bin/hypr-swap-monitors"

      # Misc
      ", Print, exec, ${grim} -g \"$(${slurp})\" - | ${swappy} -f -"
    ] ++ (
      # Workspace N
      builtins.concatMap (key: let ws = if key == "0" then "10" else key; in [
        "$mainMod, ${key}, workspace, ${ws}"
        "$mainMod SHIFT, ${key}, movetoworkspace, ${ws}"
      ]) ["1" "2" "3" "4" "5" "6" "7" "8" "9" "0"]
    ) ++ (
      # Focus arrows
      builtins.concatMap (key: [
        "$mainMod, ${key}, movefocus, ${builtins.substring 0 1 key}"
        "$mainMod, ${key}, alterzorder, top"
      ]) ["left" "right" "up" "down"]
    );

    bindm = [
      "$mainMod, mouse:272, movewindow"
      "$mainMod, mouse:273, resizewindow"
    ];

    bindel = [
      ",XF86AudioRaiseVolume, exec, wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ 5%+"
      ",XF86AudioLowerVolume, exec, wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%-"
      ",XF86AudioMute, exec, wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle"
      ",XF86AudioMicMute, exec, wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle"
      ",XF86MonBrightnessUp, exec, brightnessctl -e4 -n2 set 5%+"
      ",XF86MonBrightnessDown, exec, brightnessctl -e4 -n2 set 5%-"
    ];

    # 터치패드 제스쳐, 3손가락 쓸어넘기로 워크스페이스 전환
    gesture = "3, horizontal, workspace";
  };
}
