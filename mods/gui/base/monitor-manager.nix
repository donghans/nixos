# 화면 관리: displayctl(CLI) + displayui(TUI, Textual) — 본체는 mods/_tools/desktop/monitor-manager/
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
  src = name: builtins.readFile (../../_tools/desktop/monitor-manager + "/${name}");

  # displayctl.py(얇은 진입점)와 displayui.py, 본체 패키지 dispctl/ 를 한 디렉터리에 둔다(displayui.py 가 `import displayctl` 하므로 같은 디렉터리여야 함).
  # Nix 자리표시자(@hyprctl@, @notify_send@)는 dispctl/config.py 한 곳에만 있다.
  dispctlModules = ["__init__" "hypr" "state" "layout" "apply" "transaction" "ops" "brightness" "cli" "observelog"];
  dir = pkgs.runCommand "display-py" {} ''
    mkdir -p $out/dispctl
    cp ${pkgs.writeText "displayctl.py" (src "displayctl.py")} $out/displayctl.py
    cp ${pkgs.writeText "displayui.py" (src "displayui.py")} $out/displayui.py
    cp ${../../_tools/_lib/uikit/uikit.py} $out/uikit.py
    cp ${../../_tools/observe/observe/observe_core.py} $out/observe_core.py   # 이벤트 로그(observe_events). 못 찾아도 dispctl/observelog.py 가 무동작 대체를 씀
    cp ${../../_tools/observe/observe/observe_events.py} $out/observe_events.py
    cp ${pkgs.writeText "config.py" (builtins.replaceStrings ["@hyprctl@" "@notify_send@"] [hyprctl "${pkgs.libnotify}/bin/notify-send"] (src "dispctl/config.py"))} $out/dispctl/config.py
    ${lib.concatMapStrings (n: "cp ${pkgs.writeText "${n}.py" (src "dispctl/${n}.py")} $out/dispctl/${n}.py\n") dispctlModules}
  '';
  # brightnessctl 은 밝기 기억·절전 낮춤(dispctl/brightness.py)이 쓴다
  displayctl = pkgs.writeShellScriptBin "displayctl" ''
    export DISPLAYCTL_BRIGHTNESSCTL="''${DISPLAYCTL_BRIGHTNESSCTL:-${pkgs.brightnessctl}/bin/brightnessctl}"
    exec ${py}/bin/python3 ${dir}/displayctl.py "$@"
  '';
  displayui = pkgs.writeShellScriptBin "displayui" ''
    export DISPLAYCTL_BRIGHTNESSCTL="''${DISPLAYCTL_BRIGHTNESSCTL:-${pkgs.brightnessctl}/bin/brightnessctl}"
    exec ${py}/bin/python3 ${dir}/displayui.py "$@"
  '';
  laptop = config.workspace.type == "laptop";
  dimDelays = [30 60 120 300]; # dispctl/brightness.py 의 DELAYS 와 같아야 함(displayui 에서 고르는 값마다 hypridle 리스너가 하나씩 필요)

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
  stateDir = "/home/${config.workspace.username}/.local/state/displayctl";
in {
  # 노트북: 로그인 화면(greetd)·TTY(kmscon)에는 사용자 세션의 감시 서비스가 없으므로 시스템 서비스가 기억한 밝기를 적용한다.
  #  - 부팅: systemd-backlight(직전 밝기 복원)가 끝난 뒤, greetd/getty 보다 먼저
  #  - 전원 변경(AC↔배터리): udev 가 같은 서비스를 다시 시작(로그인 전에도 반영)
  # 밝기 기억 파일은 사용자 홈의 것을 그대로 읽는다(쓰기는 사용자 감시 서비스만). 백라이트는 커널 전역이라 Wayland 로 넘어가도 유지된다.
  os = lib.mkIf laptop {
    systemd.services.display-brightness-restore = {
      description = "Apply per-power-source remembered brightness (login screen / TTY)";
      after = ["systemd-udevd.service" "local-fs.target"];
      before = ["greetd.service" "getty.target" "display-manager.service"];
      wantedBy = ["multi-user.target"];
      serviceConfig = {
        Type = "oneshot";
        Environment = ["DISPLAYCTL_STATE=${stateDir}" "DISPLAYCTL_BRIGHTNESSCTL=${pkgs.brightnessctl}/bin/brightnessctl" "PATH=${lib.makeBinPath [pkgs.systemd]}"];
        ExecStart = "${displayctl}/bin/displayctl brightness restore";
      };
    };
    services.udev.extraRules = ''
      SUBSYSTEM=="power_supply", ATTR{type}=="Mains", ACTION=="change", TAG+="systemd", ENV{SYSTEMD_WANTS}+="display-brightness-restore.service"
    '';
  };

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

    # 노트북: 전원(AC/배터리)별 마지막 밝기를 기억해 전원이 바뀔 때 복귀시키는 감시 서비스(2초 폴링, 변화 없으면 파일 쓰기 없음).
    # 데스크톱은 백라이트가 없어 만들지 않는다(만들어도 즉시 종료).
    systemd.user.services.display-brightness = lib.mkIf laptop {
      Unit = {
        Description = "Remember and restore per-power-source brightness (displayctl brightness watch)";
        After = ["graphical-session.target"];
        PartOf = ["graphical-session.target"];
      };
      Service = {
        ExecStart = "${displayctl}/bin/displayctl brightness watch";
        Restart = "on-failure";
        RestartSec = 5;
      };
      Install.WantedBy = ["graphical-session.target"];
    };

    # 배터리에서 입력이 없을 때 밝기 낮춤: displayui 에서 고른 시간과 같은 리스너만 실제로 동작한다(나머지는 즉시 반환). 입력이 돌아오면 wake.
    services.hypridle.settings.listener = lib.mkIf laptop (map (t: {
        timeout = t;
        on-timeout = "${displayctl}/bin/displayctl brightness idle ${toString t}";
        on-resume = "${displayctl}/bin/displayctl brightness wake";
      })
      dimDelays);

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
