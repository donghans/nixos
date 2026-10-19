# 화면 관리: displayctl(CLI) + displayui(TUI, Textual) — 본체는 mods/_data/display/
#  - 화면 모드(확장/미러/노트북만/외부만), 프리젠테이션 등 프리셋(해상도 고정, 이전 구성 복귀)
#  - 모니터별 해상도·주사율·배율·상대 위치. 모니터가 알려 주는 모드 외의 값도 시도하고 적용 뒤 실제 값을 검증
#  - 해상도/주사율 변경은 확인이 없으면 되돌림: TUI 확인 창과 별개로 systemd 사용자 타이머가 예약돼서 TUI/터미널이 죽어도 되돌려짐
#  - 구성은 상태 파일에 저장하고, 시작/설정 reload/모니터 연결·해제 때 displayctl restore 로 다시 적용
#    (Hyprland 는 reload 때 런타임 모니터 설정을 지움)
# 열기: 단축키(SUPER+P, Fn+F11=XF86Display) = 화면 모드에서 시작, 토글, 모드를 고르면 적용하고 닫힘
#       앱 런처의 "Display Settings" = 주사율에서 시작(해상도/주사율/배율/위치를 만지는 용도)
{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  pkgs,
  lib,
  config,
  ...
}: let
  kitty = "${pkgs.kitty}/bin/kitty";
  uwsm = "${pkgs.uwsm}/bin/uwsm";
  jq = "${pkgs.jq}/bin/jq";
  hyprctl = "${pkgs.hyprland}/bin/hyprctl";
  py = pkgs.python3.withPackages (ps: [ps.textual]);
  src = name: builtins.readFile (../../_data/display + "/${name}");

  # displayctl.py(얇은 진입점)와 displayui.py, 본체 패키지 dispctl/ 를 한 디렉터리에 둔다(displayui.py 가 `import displayctl` 하므로 같은 디렉터리여야 함).
  # Nix 자리표시자(@hyprctl@, @notify_send@)는 dispctl/config.py 한 곳에만 있다.
  dispctlModules = ["__init__" "hypr" "state" "layout" "apply" "transaction" "ops" "cli"];
  dir = pkgs.runCommand "display-py" {} ''
    mkdir -p $out/dispctl
    cp ${pkgs.writeText "displayctl.py" (src "displayctl.py")} $out/displayctl.py
    cp ${pkgs.writeText "displayui.py" (src "displayui.py")} $out/displayui.py
    cp ${pkgs.writeText "config.py" (builtins.replaceStrings ["@hyprctl@" "@notify_send@"] [hyprctl "${pkgs.libnotify}/bin/notify-send"] (src "dispctl/config.py"))} $out/dispctl/config.py
    ${lib.concatMapStrings (n: "cp ${pkgs.writeText "${n}.py" (src "dispctl/${n}.py")} $out/dispctl/${n}.py\n") dispctlModules}
  '';
  displayctl = pkgs.writeShellScriptBin "displayctl" ''exec ${py}/bin/python3 ${dir}/displayctl.py "$@"'';
  displayui = pkgs.writeShellScriptBin "displayui" ''exec ${py}/bin/python3 ${dir}/displayui.py "$@"'';

  # 전용 창(class=displayui)으로 열기.
  #  --toggle : 이미 떠 있으면 닫기 (단축키용)
  #  그 외 인자는 displayui 로 전달. 이미 떠 있으면 닫고 새로 열어서 --focus 가 반영되게 함
  displayuiOpen = pkgs.writeShellScriptBin "displayui-open" ''
    toggle=0
    args=()
    for a in "$@"; do
      if [ "$a" = "--toggle" ]; then toggle=1; else args+=("$a"); fi
    done
    pids=$(${hyprctl} clients -j | ${jq} -r '.[] | select(.class == "displayui") | .pid')
    if [ -n "$pids" ]; then
      kill $pids
      [ "$toggle" = 1 ] && exit 0
      sleep 0.3
    fi
    exec ${uwsm} app -- ${kitty} --class displayui --title "화면 관리" ${displayui}/bin/displayui "''${args[@]}"
  '';
in {
  hm = {
    home.packages = [displayctl displayui displayuiOpen];

    # 사용 모드 허브 소비자: 세워서 쓰는 중(tent/tablet)에 기기를 돌리면 내장 화면을 같이 돌림. laptop 으로 돌아오면 0. (멱등: 이미 그 방향이면 아무것도 안 함)
    # 회전은 상태 파일에 기록돼 restore/레이아웃 변경 때도 유지됨. 방향 판정은 posture-daemon(가속도 센서). 이 기기 외 노트북은 센서가 없으면 항상 0.
    posture.consumers = lib.optionals config.workspace.convertible ["${displayctl}/bin/displayctl rotate auto"];

    # 앱 런처(SUPER+Space)에서 "Display Settings" 로 검색됨. 주사율/해상도 설정에 포커스를 두고 열림
    xdg.desktopEntries.displayui = {
      name = "Display Settings";
      genericName = "Display layout, resolution and refresh rate";
      comment = "Extend/mirror/laptop-only/external-only, presentation presets, resolution, refresh rate, scale and monitor position";
      exec = "${displayuiOpen}/bin/displayui-open --focus refresh";
      terminal = false;
      categories = ["Settings" "HardwareSettings"];
      icon = "preferences-desktop-display";
    };

    wayland.windowManager.hyprland.extraConfig = ''
      -- 화면 관리 TUI 창: 모니터 크기에 비례해 가운데에
      hl.window_rule({
        match = { class = "^(displayui)$" },
        center = true,
        size = { "monitor_w * 0.6", "monitor_h * 0.7" }
      })

      -- 화면 전환 키(SUPER+P, Fn+F11 = XF86Display): 화면 모드에서 시작, 다시 누르면 닫힘, 모드를 고르면 적용하고 닫힘
      hl.bind("SUPER + P", hl.dsp.exec_cmd("${displayuiOpen}/bin/displayui-open --toggle --focus mode --quick"), { description = "화면 관리: 화면 모드 선택 (Fn+F11)" })
      hl.bind("XF86Display", hl.dsp.exec_cmd("${displayuiOpen}/bin/displayui-open --toggle --focus mode --quick"))

      -- 저장된 화면 구성 복원: 시작, 설정 reload(런타임 모니터 설정이 지워짐), 모니터 연결/해제 때
      -- (모니터 연결 직후에는 Hyprland 가 기본 규칙을 적용하는 중이라 잠시 기다린 뒤 적용)
      hl.on("hyprland.start", function() hl.exec_cmd("sleep 2; ${displayctl}/bin/displayctl restore") end)
      hl.on("config.reloaded", function() hl.exec_cmd("sleep 1; ${displayctl}/bin/displayctl restore") end)
      hl.on("monitor.added", function() hl.exec_cmd("sleep 1.5; ${displayctl}/bin/displayctl restore") end)
      hl.on("monitor.removed", function() hl.exec_cmd("sleep 1; ${displayctl}/bin/displayctl restore") end)
    '';
  };
})
