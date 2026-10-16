# 화면 관리: displayctl(CLI) + displayui(TUI, Textual) — 본체는 mods/_data/display/
#  - 화면 모드(확장/미러/노트북만/외부만), 프리젠테이션 등 프리셋(해상도 고정, 이전 구성 복귀)
#  - 모니터별 해상도·주사율·배율·상대 위치. 모니터가 알려 주는 모드 외의 값도 시도하고 적용 뒤 실제 값을 검증
#  - 구성은 상태 파일에 저장하고, 시작/설정 reload/모니터 연결·해제 때 displayctl restore 로 다시 적용
#    (Hyprland 는 reload 때 런타임 모니터 설정을 지움)
# 열기: 단축키(SUPER+P, Fn+F11=XF86Display) = 화면 모드에서 시작, 토글, 모드를 고르면 적용하고 닫힘
#       앱 런처의 "Display Settings" = 주사율에서 시작(해상도/주사율/배율/위치를 만지는 용도)
{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  pkgs,
  lib,
  ...
}: let
  kitty = "${pkgs.kitty}/bin/kitty";
  uwsm = "${pkgs.uwsm}/bin/uwsm";
  jq = "${pkgs.jq}/bin/jq";
  hyprctl = "${pkgs.hyprland}/bin/hyprctl";
  py = pkgs.python3.withPackages (ps: [ps.textual]);
  src = name: builtins.readFile (../../_data/display + "/${name}");

  # displayui.py 가 displayctl.py 를 import 하므로 같은 디렉터리에 둔다
  dir = pkgs.runCommand "display-py" {} ''
    mkdir -p $out
    cp ${pkgs.writeText "displayctl.py" (builtins.replaceStrings ["@hyprctl@"] [hyprctl] (src "displayctl.py"))} $out/displayctl.py
    cp ${pkgs.writeText "displayui.py" (src "displayui.py")} $out/displayui.py
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
