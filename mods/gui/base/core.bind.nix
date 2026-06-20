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
    if [ -n "$FOCUSED" ] && [ -n "$TARGET" ]; then hyprctl dispatch swapactiveworkspaces "$FOCUSED" "$TARGET"; fi
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
      local grim = "${grim}"
      local slurp = "${slurp}"
      local satty = "${satty}"
      local capture_active_window = "${captureActiveWindow}/bin/hypr-capture-active"

      -- 기본 키바인딩
      hl.bind("SUPER + Q", hl.dsp.window.close())
      hl.bind("SUPER + SHIFT + Q", hl.dsp.exec_cmd("command -v hyprshutdown >/dev/null 2>&1 && hyprshutdown || hyprctl dispatch 'hl.dsp.exit()'"))
      hl.bind("SUPER + F", hl.dsp.window.float({ action = "toggle" }))
      hl.bind("SUPER + P", hl.dsp.exec_cmd(fuzzel))
      hl.bind("SUPER + V", hl.dsp.exec_cmd(cliphist .. " list | " .. fuzzel .. " --dmenu | " .. cliphist .. " decode | " .. wl_copy))
      hl.bind("SUPER + L", hl.dsp.exec_cmd("hyprlock"))
      hl.bind("SUPER + Hangul", hl.dsp.exec_cmd("systemctl --user restart app-org.fcitx.Fcitx5@autostart"))

      -- Special workspace
      hl.bind("SUPER + S", hl.dsp.workspace.toggle_special("magic"))
      hl.bind("SUPER + SHIFT + S", hl.dsp.window.move({ workspace = "special:magic" }))

      -- Scroll through existing workspaces
      hl.bind("SUPER + mouse_down", hl.dsp.focus({ workspace = "r-1" }))
      hl.bind("SUPER + mouse_up", hl.dsp.focus({ workspace = "r+1" }))
      hl.bind("SUPER + SHIFT + mouse_down", hl.dsp.window.move({ workspace = "r-1" }))
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
    '';
  };
})
