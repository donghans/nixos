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
  wofi = "${pkgs.wofi}/bin/wofi";

  # 앱 런처: wofi drun 선택 결과(.desktop 경로 [액션])를 uwsm scope 로 실행
  # (이유: 네이티브 앱(Zed, kitty 등)을 Hyprland 와 분리된 app.slice 로 띄워 CPU/IO weight 를 분리 — core.cgroups.nix 참고.
  #        uwsm app 은 경로가 아닌 Desktop Entry ID(foo.desktop[:action])를 받으므로 파일명으로 변환)
  # (주의: wofi 의 모드별 옵션은 `-D <모드>-<옵션>` 형식(drun-print_desktop_file). 접두사를 빼면 조용히 무시되어
  #        wofi 가 앱을 직접 실행하고 uwsm 래퍼를 건너뜀)
  appLauncher = pkgs.writeShellScriptBin "hypr-launcher" ''
    # wofi 는 단일 인스턴스가 아니라 다른 모니터에서 또 실행하면 중복으로 뜸 → 이미 떠 있으면 닫기(토글)
    # (Nix 래핑으로 프로세스 이름이 .wofi-wrapped 이므로 둘 다 매칭)
    pkill -x '(.wofi-wrapped|wofi)' && exit 0
    sel=$(${wofi} --show drun --prompt "앱 검색" -D drun-print_desktop_file=true) || exit 0
    [ -z "$sel" ] && exit 0
    file=''${sel%% *}
    action=''${sel#"$file"}
    action=''${action# }
    id=$(basename "$file")
    if [ -n "$action" ]; then
      exec ${pkgs.uwsm}/bin/uwsm app -- "$id:$action"
    else
      exec ${pkgs.uwsm}/bin/uwsm app -- "$id"
    fi
  '';

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

  # 디스플레이 모드 전환 스크립트 정의 (확장 / 미러 / 노트북만 / 외부만)
  # 노트북만·외부만: 사용하지 않는 쪽을 disabled 로 끔. 복원은 extend(= hyprctl reload).
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
        # (이유: 노트북만/외부만으로 끈 모니터는 disabled 가 남아 미러 규칙만으로는 켜지지 않음 → 먼저 초기화)
        hyprctl reload
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
      internal)
        # 노트북 화면만: 미러/규칙을 기본으로 되돌린 뒤 외부 모니터를 끔
        hyprctl reload
        for m in $INTERNALS; do
          hyprctl eval "hl.monitor({ output = \"$m\", mode = \"preferred\", position = \"0x0\", scale = 1 })"
        done
        [ -n "$EXTERNAL" ] && hyprctl eval "hl.monitor({ output = \"$EXTERNAL\", disabled = true })"
        ;;
      external)
        # 외부 화면만: 외부가 없으면 화면이 모두 꺼지므로 거부
        [ -z "$EXTERNAL" ] && { echo "외부 모니터 없음" >&2; exit 1; }
        hyprctl reload
        hyprctl eval "hl.monitor({ output = \"$EXTERNAL\", mode = \"preferred\", position = \"0x0\", scale = 1 })"
        for m in $INTERNALS; do
          hyprctl eval "hl.monitor({ output = \"$m\", disabled = true })"
        done
        ;;
      *) echo "usage: hypr-display-mode [extend|mirror|internal|external|toggle]" >&2; exit 1 ;;
    esac
  '';

  # 화면 모드 메뉴: 화면 전환 키(SUPER+P, XF86Display)로 wofi 표시 → hypr-display-mode 실행
  displayMenu = pkgs.writeShellScriptBin "hypr-display-menu" ''
    pkill -x '(.wofi-wrapped|wofi)' && exit 0
    modes="extend	확장 (노트북 + 외부)
    mirror	미러
    internal	노트북 화면만
    external	외부 화면만"
    sel=$(printf '%s\n' "$modes" | cut -f2 | ${wofi} --dmenu --cache-file /dev/null --width 420 --height 240 --prompt "화면 모드") || exit 0
    [ -z "$sel" ] && exit 0
    mode=$(printf '%s\n' "$modes" | ${pkgs.gawk}/bin/awk -F'\t' -v s="$sel" '$2 == s { print $1 }')
    [ -n "$mode" ] && exec ${displayMode}/bin/hypr-display-mode "$mode"
  '';

  # 단축키 목록 보기: description 이 있는 바인딩만 hyprctl 에서 읽어 wofi 로 표시
  keybindsHelp = pkgs.writeShellScriptBin "hypr-keybinds" ''
    pkill -x '(.wofi-wrapped|wofi)' && exit 0
    hyprctl binds -j | ${pkgs.jq}/bin/jq -r '
      def mods: . as $m
        | [ [64, "SUPER"], [4, "CTRL"], [8, "ALT"], [1, "SHIFT"] ][]
        | select((($m / .[0] | floor) % 2) == 1) | .[1];
      def keyname: {"mouse:272": "Mouse Left", "mouse:273": "Mouse Right", "mouse:274": "Mouse Middle", "mouse:275": "Mouse Back", "mouse:276": "Mouse Forward", "mouse_up": "Mouse Wheel Up", "mouse_down": "Mouse Wheel Down"}[.] // .;
      .[] | select(.description != "")
      | ([(.modmask | mods), (.key | keyname)] | join(" + ")) + "\t" + .description
    ' | ${pkgs.util-linux}/bin/column -t -s "$(printf '\t')" -o "   │   " \
      | ${wofi} --dmenu --cache-file /dev/null --width 900 --height 640 --prompt "단축키 검색" > /dev/null
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
    # (이유: 장치 메뉴(hypr-device-menu)가 PATH 로 호출함)
    home.packages = [displayMode];

    wayland.windowManager.hyprland.extraConfig = ''
      -- absolute paths from Nix
      local wofi = "${wofi}"
      local launcher = "${appLauncher}/bin/hypr-launcher"
      local swap_monitors = "${swapMonitors}/bin/hypr-swap-monitors"
      local display_menu = "${displayMenu}/bin/hypr-display-menu"
      local keybinds_help = "${keybindsHelp}/bin/hypr-keybinds"
      local grim = "${grim}"
      local slurp = "${slurp}"
      local satty = "${satty}"
      local capture_active_window = "${captureActiveWindow}/bin/hypr-capture-active"

      -- 설명(description)이 붙은 바인딩 헬퍼: SUPER+H 단축키 목록(hypr-keybinds)에 표시됨
      local function bindd(keys, dispatcher, desc, flags)
        flags = flags or {}
        flags.description = desc
        hl.bind(keys, dispatcher, flags)
      end

      -- 기본 키바인딩
      bindd("SUPER + Q", hl.dsp.window.close(), "창 닫기")
      bindd("SUPER + SHIFT + Q", hl.dsp.exec_cmd("command -v hyprshutdown >/dev/null 2>&1 && hyprshutdown || hyprctl dispatch 'hl.dsp.exit()'"), "Hyprland 종료")
      bindd("SUPER + F", hl.dsp.window.float({ action = "toggle" }), "플로팅 토글")
      bindd("SUPER + space", hl.dsp.exec_cmd(launcher), "앱 런처 (wofi)")
      bindd("SUPER + L", hl.dsp.exec_cmd("hyprlock"), "화면 잠금")
      bindd("SUPER + H", hl.dsp.exec_cmd(keybinds_help), "단축키 목록 보기")
      bindd("SUPER + Hangul", hl.dsp.exec_cmd("systemctl --user restart app-org.fcitx.Fcitx5@autostart"), "fcitx5 재시작")

      -- 디스플레이 모드 전환 (확장 <-> 미러)
      -- Fn+F11 은 펌웨어가 SUPER+P(Windows 의 Win+P 방식)를 보내므로 SUPER+P 에 할당
      bindd("SUPER + P", hl.dsp.exec_cmd(display_menu), "화면 모드 메뉴: 확장 / 미러 / 노트북만 / 외부만 (Fn+F11)")
      hl.bind("XF86Display", hl.dsp.exec_cmd(display_menu))

      -- Special workspace
      bindd("SUPER + S", hl.dsp.workspace.toggle_special("magic"), "스페셜 워크스페이스 토글")
      bindd("SUPER + SHIFT + S", hl.dsp.window.move({ workspace = "special:magic" }), "창을 스페셜 워크스페이스로 보내기")

      -- Scroll through existing workspaces
      bindd("SUPER + mouse_down", hl.dsp.focus({ workspace = "r-1" }), "이전 워크스페이스 (휠)")
      bindd("SUPER + mouse_up", hl.dsp.focus({ workspace = "r+1" }), "다음 워크스페이스 (휠)")
      bindd("SUPER + SHIFT + mouse_down", hl.dsp.window.move({ workspace = "r-1" }), "창을 이전 워크스페이스로 (휠)")
      bindd("SUPER + SHIFT + mouse_up", hl.dsp.window.move({ workspace = "r+1" }), "창을 다음 워크스페이스로 (휠)")
      bindd("SUPER + SHIFT + CTRL + mouse_down", hl.dsp.window.move({ workspace = "r-1", follow = false }), "창을 이전 워크스페이스로, 따라가지 않음 (휠)")
      bindd("SUPER + SHIFT + CTRL + mouse_up", hl.dsp.window.move({ workspace = "r+1", follow = false }), "창을 다음 워크스페이스로, 따라가지 않음 (휠)")

      -- Swap workspaces
      bindd("SUPER + SHIFT + mouse:274", hl.dsp.exec_cmd(swap_monitors), "모니터 간 워크스페이스 스왑")

      -- Misc
      bindd("Print", hl.dsp.exec_cmd(grim .. " -g \"$(" .. slurp .. ")\" - | " .. satty .. " --filename -"), "영역 캡처")
      bindd("CTRL + Print", hl.dsp.exec_cmd(capture_active_window), "현재 창 캡처")
      bindd("SHIFT + Print", hl.dsp.exec_cmd(grim .. " - | " .. satty .. " --filename -"), "전체 화면 캡처")

      ${lib.optionalString config.services.custom-notify-logger.enable ''
        bindd("SUPER + N", hl.dsp.exec_cmd("pkill -x '(.wofi-wrapped|wofi)' && exit 0; ls -tr ${config.services.custom-notify-logger.logDir}/$USER.log* 2>/dev/null | xargs -r zcat -f | tac | " .. wofi .. " --dmenu --cache-file /dev/null --width 1400 --prompt \"알림 검색 (최근 30일)\""), "알림 로그 (30일)")
      ''}

      -- Workspace 1-10
      for i = 1, 9 do
        bindd("SUPER + " .. tostring(i), hl.dsp.focus({ workspace = tostring(i) }), "워크스페이스 " .. i .. " 로 이동")
        bindd("SUPER + SHIFT + " .. tostring(i), hl.dsp.window.move({ workspace = tostring(i) }), "창을 워크스페이스 " .. i .. " 로 보내기")
      end
      bindd("SUPER + 0", hl.dsp.focus({ workspace = "10" }), "워크스페이스 10 로 이동")
      bindd("SUPER + SHIFT + 0", hl.dsp.window.move({ workspace = "10" }), "창을 워크스페이스 10 로 보내기")

      -- Focus arrows
      local directions = {
        left = "l",
        right = "r",
        up = "u",
        down = "d"
      }
      for key, dir in pairs(directions) do
        bindd("SUPER + " .. key, function()
          hl.dispatch(hl.dsp.focus({ direction = dir }))
          hl.dispatch(hl.dsp.window.alter_zorder({ mode = "top" }))
        end, "포커스 이동 (" .. key .. ")")
      end

      -- Mouse drag (bindm)
      bindd("SUPER + mouse:272", hl.dsp.window.drag(), "창 이동", { mouse = true })
      bindd("SUPER + mouse:273", hl.dsp.window.resize(), "창 크기 조절", { mouse = true })

      -- Release bindings (bindr)
      bindd("SUPER + SHIFT + Hangul", hl.dsp.exec_cmd("systemctl --user restart app-org.fcitx.Fcitx5@autostart"), "fcitx5 재시작 (키를 뗄 때)", { release = true })

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
