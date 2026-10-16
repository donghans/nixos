{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  pkgs,
  config,
  lib,
  ...
}: let
  # 사용되는 명령어의 파일 경로 정의
  grim = "${pkgs.grim}/bin/grim";
  slurp = "${pkgs.slurp}/bin/slurp";
  satty = "${pkgs.satty}/bin/satty";
  cliphist = "${pkgs.cliphist}/bin/cliphist";
  fuzzel = "${pkgs.fuzzel}/bin/fuzzel";
  wl-copy = "${pkgs.wl-clipboard}/bin/wl-copy";

  # 모니터 스왑 스크립트 정의
  swapMonitors = pkgs.writeShellScriptBin "hypr-swap-monitors" ''
    # jq로 현재 포커스된 모니터와 첫 번째 비포커스 모니터를 명확히 추출
    MONITORS_JSON=$(hyprctl monitors -j)
    FOCUSED=$(echo "$MONITORS_JSON" | ${pkgs.jq}/bin/jq -r '.[] | select(.focused == true) | .name')
    TARGET=$(echo "$MONITORS_JSON" | ${pkgs.jq}/bin/jq -r '.[] | select(.focused == false) | .name' | head -n 1)

    # dispatch 명령어 실행
    if [ -n "$FOCUSED" ] && [ -n "$TARGET" ]; then
      hyprctl dispatch "hl.dsp.workspace.swap_monitors({ monitor1 = \"$FOCUSED\", monitor2 = \"$TARGET\" })"
    fi
  '';

  # 디스플레이 모드 전환 스크립트 정의 (확장 <-> 미러)
  # 미러: 내부 모니터(eDP-*)가 외부 모니터의 화면/비율을 그대로 따라감 (패널 비율이 다르면 여백 발생)
  # 확장: hyprctl reload 로 설정 파일의 기본 monitor 규칙 복원
  displayMode = pkgs.writeShellScriptBin "hypr-display-mode" ''
    JQ=${pkgs.jq}/bin/jq
    # 미러된 모니터는 `monitors`에서 빠지므로 all 로 조회
    MONITORS_JSON=$(hyprctl monitors all -j)
    EXTERNAL=$(echo "$MONITORS_JSON" | $JQ -r '[.[] | select(.name | startswith("eDP") | not)] | .[0].name // empty')
    INTERNALS=$(echo "$MONITORS_JSON" | $JQ -r '.[] | select(.name | startswith("eDP")) | .name')
    MIRRORED=$(echo "$MONITORS_JSON" | $JQ -r '[.[] | select(.name | startswith("eDP")) | select(.mirrorOf != "none")] | length')

    MODE=''${1:-toggle}
    if [ "$MODE" = toggle ]; then
      if [ "$MIRRORED" -gt 0 ]; then MODE=extend; else MODE=mirror; fi
    fi

    case "$MODE" in
      mirror)
        [ -z "$EXTERNAL" ] && { echo "외부 모니터 없음" >&2; exit 1; }
        for m in $INTERNALS; do
          hyprctl eval "hl.monitor({ output = \"$m\", mode = \"preferred\", position = \"auto\", scale = 1, mirror = \"$EXTERNAL\" })"
        done
        ;;
      extend)
        # reload 만으로는 내부 모니터가 외부 옆으로 밀려 배치가 바뀌므로 내부를 원점에 고정 후 외부를 위로 재배치
        hyprctl reload
        for m in $INTERNALS; do
          hyprctl eval "hl.monitor({ output = \"$m\", mode = \"preferred\", position = \"0x0\", scale = 1 })"
        done
        [ -n "$EXTERNAL" ] && hyprctl eval "hl.monitor({ output = \"$EXTERNAL\", mode = \"preferred\", position = \"auto-up\", scale = 1 })"
        ;;
      *) echo "usage: hypr-display-mode [extend|mirror|toggle]" >&2; exit 1 ;;
    esac
  '';

  # 현재 창 캡쳐 스크립트 정의
  captureActiveWindow = pkgs.writeShellScriptBin "hypr-capture-active" ''
    GEOM=$(hyprctl activewindow -j | ${pkgs.jq}/bin/jq -r 'select(.address != null) | "\(.at[0]),\(.at[1]) \(.size[0])x\(.size[1])"')
    if [ -n "$GEOM" ]; then
      ${grim} -g "$GEOM" - | ${satty} --filename -
    fi
  '';
in {
  hm = {
    wayland.windowManager.hyprland.extraConfig = ''
      -- absolute paths from Nix
      local fuzzel = "${fuzzel}"
      local cliphist = "${cliphist}"
      local wl_copy = "${wl-copy}"
      local swap_monitors = "${swapMonitors}/bin/hypr-swap-monitors"
      local display_mode = "${displayMode}/bin/hypr-display-mode"
      local grim = "${grim}"
      local slurp = "${slurp}"
      local satty = "${satty}"
      local capture_active_window = "${captureActiveWindow}/bin/hypr-capture-active"

      -- 기본 키바인딩
      hl.bind("SUPER + Q", hl.dsp.window.close())
      hl.bind("SUPER + SHIFT + Q", hl.dsp.exec_cmd("command -v hyprshutdown >/dev/null 2>&1 && hyprshutdown || hyprctl dispatch 'hl.dsp.exit()'"))
      hl.bind("SUPER + F", hl.dsp.window.float({ action = "toggle" }))
      hl.bind("SUPER + space", hl.dsp.exec_cmd(fuzzel))
      hl.bind("SUPER + V", hl.dsp.exec_cmd(cliphist .. " list | " .. fuzzel .. " --dmenu | " .. cliphist .. " decode | " .. wl_copy))
      hl.bind("SUPER + L", hl.dsp.exec_cmd("hyprlock"))
      hl.bind("SUPER + Hangul", hl.dsp.exec_cmd("systemctl --user restart app-org.fcitx.Fcitx5@autostart"))

      -- 디스플레이 모드 전환 (확장 <-> 미러)
      -- Fn+F11 은 펌웨어가 SUPER+P(Windows 의 Win+P 방식)를 보내므로 SUPER+P 에 할당
      hl.bind("SUPER + P", hl.dsp.exec_cmd(display_mode))
      hl.bind("XF86Display", hl.dsp.exec_cmd(display_mode))

      -- Special workspace
      hl.bind("SUPER + S", hl.dsp.workspace.toggle_special("magic"))
      hl.bind("SUPER + SHIFT + S", hl.dsp.window.move({ workspace = "special:magic" }))

      -- Scroll through existing workspaces
      hl.bind("SUPER + mouse_down", hl.dsp.focus({ workspace = "r-1" }))
      hl.bind("SUPER + mouse_up", hl.dsp.focus({ workspace = "r+1" }))
      hl.bind("SUPER + SHIFT + mouse_down", hl.dsp.window.move({ workspace = "r-1" }))
      hl.bind("SUPER + SHIFT + mouse_up", hl.dsp.window.move({ workspace = "r+1" }))
      hl.bind("SUPER + SHIFT + CTRL + mouse_down", hl.dsp.window.move({ workspace = "r-1", follow = false }))
      hl.bind("SUPER + SHIFT + CTRL + mouse_up", hl.dsp.window.move({ workspace = "r+1", follow = false }))

      -- Swap workspaces
      hl.bind("SUPER + SHIFT + mouse:274", hl.dsp.exec_cmd(swap_monitors))

      -- Misc
      hl.bind("Print", hl.dsp.exec_cmd(grim .. " -g \"$(" .. slurp .. ")\" - | " .. satty .. " --filename -"))
      hl.bind("CTRL + Print", hl.dsp.exec_cmd(capture_active_window))
      hl.bind("SHIFT + Print", hl.dsp.exec_cmd(grim .. " - | " .. satty .. " --filename -"))

      ${lib.optionalString config.services.custom-notify-logger.enable ''
        hl.bind("SUPER + N", hl.dsp.exec_cmd("ls -tr ${config.services.custom-notify-logger.logDir}/$USER.log* 2>/dev/null | xargs -r zcat -f | tac | " .. fuzzel .. " --dmenu --width 150 --placeholder \"Search 30-day History...\""))
      ''}

      -- Workspace 1-10
      for i = 1, 9 do
        hl.bind("SUPER + " .. tostring(i), hl.dsp.focus({ workspace = tostring(i) }))
        hl.bind("SUPER + SHIFT + " .. tostring(i), hl.dsp.window.move({ workspace = tostring(i) }))
      end
      hl.bind("SUPER + 0", hl.dsp.focus({ workspace = "10" }))
      hl.bind("SUPER + SHIFT + 0", hl.dsp.window.move({ workspace = "10" }))

      -- Focus arrows
      local directions = {
        left = "l",
        right = "r",
        up = "u",
        down = "d"
      }
      for key, dir in pairs(directions) do
        hl.bind("SUPER + " .. key, function()
          hl.dispatch(hl.dsp.focus({ direction = dir }))
          hl.dispatch(hl.dsp.window.alter_zorder({ mode = "top" }))
        end)
      end

      -- Mouse drag (bindm)
      hl.bind("SUPER + mouse:272", hl.dsp.window.drag(), { mouse = true })
      hl.bind("SUPER + mouse:273", hl.dsp.window.resize(), { mouse = true })

      -- Release bindings (bindr)
      hl.bind("SUPER + SHIFT + Hangul", hl.dsp.exec_cmd("systemctl --user restart app-org.fcitx.Fcitx5@autostart"), { release = true })

      -- Gestures
      hl.gesture({
        fingers = 3,
        direction = "horizontal",
        action = "workspace"
      })

      -- 3손가락 아래 스와이프: 모니터 간 워크스페이스 스왑
      hl.gesture({
        fingers = 3,
        direction = "down",
        action = function() hl.exec_cmd(swap_monitors) end
      })
    '';
  };
})
