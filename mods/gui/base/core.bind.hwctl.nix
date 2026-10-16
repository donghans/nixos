{
  mkPartOf,
  lib,
  ...
}: let
  base = mkPartOf "mods.gui" ({
    pkgs,
    lib,
    config,
    ...
  }: let
    # == Hardware Control Scripts ==
    # 볼륨 조절 및 알림 스크립트
    volumeControl = pkgs.writeShellScriptBin "vol-control" ''
      case $1 in
        up) ${pkgs.wireplumber}/bin/wpctl set-volume -l 1.0 @DEFAULT_AUDIO_SINK@ 5%+ ;;
        down) ${pkgs.wireplumber}/bin/wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%- ;;
        mute) ${pkgs.wireplumber}/bin/wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle ;;
        mic)
          ${pkgs.wireplumber}/bin/wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle
          if ${pkgs.wireplumber}/bin/wpctl get-volume @DEFAULT_AUDIO_SOURCE@ | grep -q "MUTED"; then STATE="Muted"; else STATE="On"; fi
          ${pkgs.libnotify}/bin/notify-send -h string:x-canonical-private-synchronous:microphone -u low "Microphone" "$STATE"
          exit 0 ;;
      esac

      VOL=$(${pkgs.wireplumber}/bin/wpctl get-volume @DEFAULT_AUDIO_SINK@ | awk '{print int($2*100)}')
      MUTE=$(${pkgs.wireplumber}/bin/wpctl get-volume @DEFAULT_AUDIO_SINK@ | grep -q "MUTED" && echo " (Muted)" || echo "")
      ${pkgs.libnotify}/bin/notify-send -h string:x-canonical-private-synchronous:volume -h int:value:"$VOL" -u low "Volume" "$VOL%$MUTE"
    '';

    # 밝기 조절 및 알림 스크립트
    brightnessControl = pkgs.writeShellScriptBin "brt-control" ''
      case $1 in
        up) ${pkgs.brightnessctl}/bin/brightnessctl set 5%+ ;;
        down) ${pkgs.brightnessctl}/bin/brightnessctl set 5%- ;;
      esac

      BRT=$(${pkgs.brightnessctl}/bin/brightnessctl -m | cut -d, -f4 | tr -d '%')
      ${pkgs.libnotify}/bin/notify-send -h string:x-canonical-private-synchronous:brightness -h int:value:"$BRT" -u low "Brightness" "$BRT%"
    '';

    # 터치패드 토글 스크립트 (Laptop 전용)
    toggleTouchpad = pkgs.writeShellScriptBin "hypr-toggle-touchpad" ''
      DEVICES=$(hyprctl devices -j | ${pkgs.jq}/bin/jq -r '.mice[] | select(.name | contains("touchpad")) | .name')

      if [ -z "$DEVICES" ]; then
        ${pkgs.libnotify}/bin/notify-send "Touchpad" "No touchpad device found!"
        exit 1
      fi

      STATUS_FILE="$HOME/.local/state/hypr/touchpad_enabled"
      mkdir -p "$(dirname "$STATUS_FILE")"
      [ ! -f "$STATUS_FILE" ] && echo "true" > "$STATUS_FILE"
      CURRENT_STATUS=$(cat "$STATUS_FILE")

      if [ "$CURRENT_STATUS" = "true" ]; then
        while read -r dev; do
          hyprctl eval "hl.device({ name = \"$dev\", enabled = false })"
        done <<< "$DEVICES"
        echo "false" > "$STATUS_FILE"
        ${pkgs.libnotify}/bin/notify-send -h string:x-canonical-private-synchronous:touchpad -u low "Touchpad" "Disabled"
      else
        while read -r dev; do
          hyprctl eval "hl.device({ name = \"$dev\", enabled = true })"
        done <<< "$DEVICES"
        echo "true" > "$STATUS_FILE"
        ${pkgs.libnotify}/bin/notify-send -h string:x-canonical-private-synchronous:touchpad -u low "Touchpad" "Enabled"
      fi
    '';

    # 터치스크린 토글 스크립트 (Laptop 전용). 펜(stylus)은 그대로 둠
    toggleTouchscreen = pkgs.writeShellScriptBin "hypr-toggle-touchscreen" ''
      DEVICES=$(hyprctl devices -j | ${pkgs.jq}/bin/jq -r '.touch[]?.name')

      if [ -z "$DEVICES" ]; then
        ${pkgs.libnotify}/bin/notify-send "Touchscreen" "No touchscreen device found!"
        exit 1
      fi

      # (기록이 없으면 꺼짐이 기본: 터치스크린은 평소 쓰지 않음)
      STATUS_FILE="$HOME/.local/state/hypr/touchscreen_enabled"
      mkdir -p "$(dirname "$STATUS_FILE")"
      [ ! -f "$STATUS_FILE" ] && echo "false" > "$STATUS_FILE"

      if [ "$(cat "$STATUS_FILE")" = "true" ]; then NEW=false; LABEL=Disabled; else NEW=true; LABEL=Enabled; fi
      while read -r dev; do
        hyprctl eval "hl.device({ name = \"$dev\", enabled = $NEW })"
      done <<< "$DEVICES"
      echo "$NEW" > "$STATUS_FILE"
      ${pkgs.libnotify}/bin/notify-send -h string:x-canonical-private-synchronous:touchscreen -u low "Touchscreen" "$LABEL"
    '';

    # 터치패드/터치스크린의 켜짐/꺼짐을 로그인과 Hyprland 설정 reload 뒤에도 유지(터치스크린은 기록이 없으면 꺼짐)
    # (이유: 장치 켜기/끄기(hl.device enabled)는 런타임 설정이라 hyprctl reload 때 초기화되는데 상태 기록 파일은
    #  남아서, 메뉴 표시와 실제 상태가 어긋나고 토글이 반대로 동작했음)
    restoreInput = pkgs.writeShellScriptBin "hypr-restore-input" ''
      # apply <기록 파일> <기록이 없을 때 기본값> <대상 장치 jq 식>
      apply() {
        [ "$(cat "$HOME/.local/state/hypr/$1" 2>/dev/null || echo "$2")" = false ] || return 0
        hyprctl devices -j | ${pkgs.jq}/bin/jq -r "$3" | while read -r dev; do
          hyprctl eval "hl.device({ name = \"$dev\", enabled = false })" > /dev/null
        done
      }
      apply touchpad_enabled true '.mice[] | select(.name | contains("touchpad")) | .name'
      apply touchscreen_enabled false '.touch[]?.name'
      ${pkgs.util-linux}/bin/logger -t hypr-restore-input "input device state restored"
    '';

    # 입력 장치 메뉴(터치패드/터치스크린): 터치패드 키를 누르면 wofi 로 표시. 항목 추가는 deviceMenuExtraEntries 옵션 사용
    # (화면 모드 전환은 별도 메뉴 hypr-display-menu — 화면 전환 키 SUPER+P / XF86Display)
    extraEntries = config.wayland.windowManager.hyprland.deviceMenuExtraEntries;
    deviceMenu = pkgs.writeShellScriptBin "hypr-device-menu" ''
      pkill -x '(.wofi-wrapped|wofi)' && exit 0

      labels=()
      cmds=()
      add() { labels+=("$1"); cmds+=("$2"); }
      # onoff <기록 파일> <기록이 없을 때 기본값>
      onoff() { [ "$(cat "$HOME/.local/state/hypr/$1" 2>/dev/null || echo "$2")" = true ] && echo "끄기 (지금 켜짐)" || echo "켜기 (지금 꺼짐)"; }

      add "터치패드 $(onoff touchpad_enabled true)" "${toggleTouchpad}/bin/hypr-toggle-touchpad"
      ${lib.concatMapStrings (e: "add ${lib.escapeShellArg e.label} ${lib.escapeShellArg e.command}\n      ") extraEntries}add "터치스크린 $(onoff touchscreen_enabled false)" "${toggleTouchscreen}/bin/hypr-toggle-touchscreen"
      
      sel=$(printf '%s\n' "''${labels[@]}" | ${pkgs.wofi}/bin/wofi --dmenu --hide-search --cache-file /dev/null --width 520 --lines ${toString (2 + builtins.length extraEntries)}) || exit 0
      [ -z "$sel" ] && exit 0
      for i in "''${!labels[@]}"; do
        if [ "''${labels[$i]}" = "$sel" ]; then
          exec ${pkgs.runtimeShell} -c "''${cmds[$i]}"
        fi
      done
    '';
  in {
    hm = {
      # 스크립트를 home.packages에 명시적으로 추가해 HM 클로저에 포함시킴
      # (settings.bindl 문자열 내 스토어 경로는 의존성 추적에서 누락될 수 있음)
      home.packages = lib.optionals (config.workspace.type == "laptop") [
        toggleTouchpad
        toggleTouchscreen
        restoreInput
        deviceMenu
        volumeControl
        brightnessControl
      ];

      # 로그인(hyprland.start)과 설정 reload(config.reloaded) 때 마지막 켜짐/꺼짐 상태를 복원
      # (이유: Hyprland 는 시작/reload 때 장치를 모두 켠 상태로 되돌림)
      wayland.windowManager.hyprland.extraConfig = lib.mkIf (config.workspace.type == "laptop") ''
        hl.on("hyprland.start", function()
          hl.exec_cmd("sleep 1; ${restoreInput}/bin/hypr-restore-input")
        end)
        hl.on("config.reloaded", function()
          hl.exec_cmd("${restoreInput}/bin/hypr-restore-input")
        end)
      '';

      wayland.windowManager.hyprland.settings = {
        # == Generic Media Bindings ==
        bindel =
          [
            ", XF86AudioRaiseVolume, exec, ${volumeControl}/bin/vol-control up"
            ", XF86AudioLowerVolume, exec, ${volumeControl}/bin/vol-control down"
            ", XF86AudioMute, exec, ${volumeControl}/bin/vol-control mute"
            ", XF86AudioMicMute, exec, ${volumeControl}/bin/vol-control mic"
          ]
          ++ lib.optionals (config.workspace.type == "laptop") [
            ", XF86MonBrightnessUp, exec, ${brightnessControl}/bin/brt-control up"
            ", XF86MonBrightnessDown, exec, ${brightnessControl}/bin/brt-control down"
          ];

        # == Laptop Specific Bindings ==
        bindl = lib.mkIf (config.workspace.type == "laptop") [
          # 입력 장치 메뉴 (터치패드 키)
          # (이전에는 터치패드를 바로 토글했음. 이제는 입력 장치 메뉴를 띄우고, 터치패드 토글은 메뉴 항목으로 이동)
          "${config.wayland.windowManager.hyprland.touchpadToggleKey}, exec, ${deviceMenu}/bin/hypr-device-menu"

          # 덮개 스위치 (로그인 잠금 및 전원 관리)
          ", switch:on:Lid Switch, exec, loginctl lock-session && hyprctl dispatch \"hl.dsp.dpms({ action = 'disable' })\"${lib.optionalString (config.wayland.windowManager.hyprland.lidSwitchOnExtraCmd != "") " && ${config.wayland.windowManager.hyprland.lidSwitchOnExtraCmd}"}"
          ", switch:off:Lid Switch, exec, hyprctl dispatch \"hl.dsp.dpms({ action = 'enable' })\"${lib.optionalString (config.wayland.windowManager.hyprland.lidSwitchOffExtraCmd != "") " && ${config.wayland.windowManager.hyprland.lidSwitchOffExtraCmd}"}"
        ];
      };
    };
  });
in {
  inherit (base) imports;

  # (주의: options는 mkIf로 감쌀 수 없으므로 항상 선언)
  options.wayland.windowManager.hyprland = {
    touchpadToggleKey = lib.mkOption {
      type = lib.types.str;
      default = ", XF86TouchpadToggle";
      description = "Touchpad toggle key binding for Hyprland.";
    };
    deviceMenuExtraEntries = lib.mkOption {
      type = lib.types.listOf (lib.types.submodule {
        options = {
          label = lib.mkOption {
            type = lib.types.str;
            description = "메뉴에 표시할 이름";
          };
          command = lib.mkOption {
            type = lib.types.str;
            description = "선택 시 실행할 셸 명령";
          };
        };
      });
      default = [];
      description = "입력 장치 메뉴(hypr-device-menu)에 추가할 항목. 호스트 전용 동작(예: 특정 터치패드 드라이버 재시작)용.";
    };
    lidSwitchOnExtraCmd = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "Extra command to run when lid is closed (switch:on).";
    };
    lidSwitchOffExtraCmd = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "Extra command to run when lid is opened (switch:off).";
    };
  };
}
