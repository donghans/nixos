# observectl / observe — 관측 시스템: 전력/프로세스/C-state 수집기(root), 우리 유틸리티의 구조화 이벤트 로그, 프로파일·타임라인·A/B 통계 CLI
#  - 본체는 mods/_data/observe/ (설명은 파일 머리말과 _docs/content/explanation/observectl.md).
#  - 켜고 끄기: `observectl on [L0|L1]` / `observectl off` — 제어 파일(/var/lib/observe/control.json, 그룹 users 쓰기 가능)만 바꾼다.
#    수집기는 systemd **path 유닛**이 제어 파일 변경/요청 디렉터리에 파일이 생길 때만 띄우고, 꺼져 있고 할 일이 없으면 15초 뒤 스스로 종료한다
#    (꺼져 있는 동안 프로세스가 없으므로 측정에 영향을 주지 않는다. 켜져 있을 때의 오버헤드는 `observectl ab` 로 직접 재서 power-evidence.md 에 기록).
#  - 개인정보: 프로세스는 comm 과 exe 이름만, 명령 인자·URL·입력한 글자는 기록하지 않는다.
#  - Netdata(1초/10초 간격 시스템 지표, 7일)는 그대로 둔다. observectl 는 Netdata 가 못 보는 것(스레드·깨움 원인·패키지 C-state·유틸리티 이벤트·실험 표지)을 맡는다.
{mkMod, ...}:
mkMod __curPos "observectl (관측: 수집기 · 이벤트 로그 · 프로파일/타임라인/A-B CLI)" ({
  config,
  lib,
  pkgs,
  ...
}: let
  py = pkgs.python3;
  dir = pkgs.runCommand "observe-src" {} ''
    mkdir -p $out
    ${lib.concatMapStringsSep "\n" (f: "cp ${../../_data/observe + "/${f}"} $out/${f}") ["observe_core.py" "observe_events.py" "observe_stats.py" "observe_collector.py" "observe_cli.py" "observe_emit.py" "observe_trace.py" "observe_bpf.py" "observe_netdata.py" "observe_explain.py" "observe_tiers.py" "observe_apps.py" "observe_query.py" "observe_focus.py" "observe_browser.py" "observe_fleet.py" "usagegraph.py" "usagechart.py" "usagedata.py" "usagespikes.py" "usageview.py" "usagelive.py" "usageui.py"]}
    # procui(프로세스 관리 TUI) — 같은 디렉터리의 observe_apps·hostmetrics·uikit 을 import 하므로 한 디렉터리에 둔다
    ${lib.concatMapStringsSep "\n" (f: "cp ${../../_data/procui + "/${f}"} $out/${f}") ["procscan.py" "procgroups.py" "procactions.py" "procplan.py" "procui.py" "procctl.py"]}
    cp ${../../_data/observe/examples/power_knobs.py} $out/power_knobs.py
    cp ${../../_data/_uikit/uikit.py} $out/uikit.py
    # 호스트 측정·판정 모듈의 정본은 donghans-host-resources 스킬 폴더(복제본을 따로 두지 않는다). usageui 실시간 탭·procui 가 import 한다
    cp ${../../_data/claude-skills/donghans-host-resources/scripts/hostmetrics.py} $out/hostmetrics.py
  '';
  # fleet(호스트 간 비교)가 공유 저장소(Postgres)에 붙으므로 psycopg 가 있는 파이썬으로 실행한다(다른 하위 명령은 표준 라이브러리만 쓴다)
  pyDb = py.withPackages (ps: [ps.psycopg]);
  observectl = pkgs.writeShellScriptBin "observectl" ''exec ${pyDb}/bin/python3 ${dir}/observe_cli.py "$@"'';
  # 전력·자원 사용 습관 TUI(Textual) — 같은 디렉터리의 observe_core 를 import 하므로 dir 에서 실행한다
  usageui = pkgs.writeShellScriptBin "usageui" ''exec ${pkgs.python3.withPackages (ps: [ps.textual])}/bin/python3 ${dir}/usageui.py "$@"'';
  # 프로세스 관리 TUI(Textual) — usageui(읽기 전용 모니터)와 분리한 조치 도구. 그룹·필터·보호·안전한 일괄 종료
  procui = pkgs.writeShellScriptBin "procui" ''exec ${pkgs.python3.withPackages (ps: [ps.textual])}/bin/python3 ${dir}/procui.py "$@"'';
  # LLM·사람용 비대화형 프로세스 정리 CLI(plan→apply→escalate). textual 이 필요 없어 기본 파이썬으로 실행한다
  procctl = pkgs.writeShellScriptBin "procctl" ''exec ${py}/bin/python3 ${dir}/procctl.py "$@"'';
  observeEmit = pkgs.writeShellScriptBin "observe-emit" ''exec ${py}/bin/python3 ${dir}/observe_emit.py "$@"'';
in {
  # 창 수명·포커스 구간(스팬) 기록: Hyprland 이벤트 소켓을 읽어 observectl trace --comp windows 로 앱별 포커스 시간·에너지를 본다(앱 수정 없음, 창 제목은 기록 안 함).
  # 이벤트가 올 때만 깨어난다. Hyprland 가 끝나 소켓이 닫히면 열린 구간을 닫고 스스로 끝난다(재시작 정책은 두지 않음 — 다음 로그인에 다시 뜸).
  hm.systemd.user.services.observe-focus = {
    Unit = {
      Description = "Record Hyprland window/focus spans for observectl";
      PartOf = ["graphical-session.target"];
      After = ["graphical-session.target"];
    };
    Service = {
      ExecStart = "${py}/bin/python3 ${dir}/observe_focus.py";
      Environment = ["PATH=${lib.makeBinPath [pkgs.hyprland]}"]; # 시작할 때 이미 열린 창을 읽는 hyprctl
      Nice = 10;
    };
    Install.WantedBy = ["graphical-session.target"];
  };

  # 브라우저(Vivaldi) CPU 폭주 감시: 평소에는 /proc 만 보고(15초마다 가볍게), 합계 CPU 가 30% 이상인 폴이 2번 연속이면 디버깅 포트(127.0.0.1:9222)로
  # 탭·확장별 CPU 를 5초 재서 `browser.burst` 이벤트로 남긴다(`observectl browser bursts`). 읽기 전용(Performance.getMetrics·탭 목록만), 제목·주소는 저장 안 함 — 호스트 이름만.
  # 전제: Vivaldi 를 --remote-debugging-port=9222 로 시작(mods/gui/apps/vivaldi.nix). 포트가 없으면 /proc 합계만 기록한다. 재시작 정책은 두지 않는다(문제가 생기면 그때 수정).
  hm.systemd.user.services.observe-browser = {
    Unit = {
      Description = "Watch browser CPU bursts and attribute them to tabs (read-only CDP)";
      PartOf = ["graphical-session.target"];
      After = ["graphical-session.target"];
    };
    Service = {
      ExecStart = "${py}/bin/python3 ${dir}/observe_browser.py";
      Nice = 10;
    };
    Install.WantedBy = ["graphical-session.target"];
  };

  # 호스트 간 비교용 요약 올리기: 6시간마다 `observectl fleet push`(최근 26시간, 멱등) — 시간별 앱 CPU·전력 평균과 브라우저 확장 목록만(원본 표본·창 제목·주소 없음).
  # 서버(claude-ctx)에 못 붙으면 실패로 남을 뿐 다음 주기에 다시 한다(Persistent). 노트북은 수집이 꺼져 있으면 확장 목록만 올라간다. 데이터 설명은 observe_fleet.py 머리말.
  hm.systemd.user.services.observe-fleet-push = {
    Unit.Description = "Push observectl hourly summaries to the shared store (claude_ctx) for cross-host comparison";
    Service = {
      Type = "oneshot";
      ExecStart = "${observectl}/bin/observectl fleet push";
      Nice = 15;
    };
  };
  hm.systemd.user.timers.observe-fleet-push = {
    Unit.Description = "Cross-host observe summary push (every 6 hours)";
    Timer = {
      OnCalendar = "*-*-* 00/6:17:00";
      Persistent = true;
      RandomizedDelaySec = "10m";
    };
    Install.WantedBy = ["timers.target"];
  };

  # 앱 런처(SUPER+Space)에서도 열리도록 등록(터미널 앱이라 uwsm 이 xdg-terminal-exec 로 kitty 에 띄움)
  hm.xdg.desktopEntries.usageui = {
    name = "Usage Monitor";
    genericName = "Power and resource usage";
    comment = "Battery, power, app usage and what changed — from the observectl collector";
    exec = "${usageui}/bin/usageui";
    terminal = true;
    categories = ["System" "Monitor"];
    icon = "utilities-system-monitor";
  };

  hm.xdg.desktopEntries.procui = {
    name = "Process Manager";
    genericName = "Group, filter and safely stop processes";
    comment = "procui — 프로세스를 그룹으로 보고 보호 규칙을 지키며 종료";
    exec = "${procui}/bin/procui";
    terminal = true;
    categories = ["System" "Monitor"];
    icon = "utilities-system-monitor";
  };

  os = {
    environment.systemPackages = [observectl observeEmit usageui procui procctl];

    # MSR(패키지 C-state 잔여율)을 읽으려면 msr 모듈이 필요(root 만 접근). 수집기가 없을 때 modprobe 도 시도하지만 부팅 때 올려 둔다.
    boot.kernelModules = ["msr"];

    # 호스트 종류별 수집 기본값(분기): 노트북은 목표가 배터리 사용량 관리·개선이라 측정에 변수를 섞지 않도록 **기본 꺼짐**(`observectl on` 으로 필요할 때만),
    # 그 밖(데스크톱·서버)은 목표가 비효율 프로세스 관리·집중할 곳에 자원 쓰기라 나중에 "아까 왜 느렸나"를 보려면 쌓여 있어야 하므로 **기본 켜짐**.
    # 사용자가 `observectl on|off` 로 control.json 에 쓴 값은 이 기본값보다 항상 우선한다(observe_core.DEFAULT_ENABLED_FLAG).
    environment.etc."observe/default-enabled" = lib.mkIf (config.workspace.type != "laptop") {text = "";};

    systemd.tmpfiles.rules = [
      "d /var/lib/observe 0775 root users -"
      "d /var/lib/observe/requests 1777 root root -"
      "d /var/lib/observe/results 0755 root root -"
      "d /var/lib/observe/data 0755 root root -"
      "f /var/lib/observe/control.json 0664 root users - {}"
    ];

    systemd.services.observe-collector = {
      description = "observectl collector (power/C-state/process profiler; starts on demand)";
      wantedBy = ["multi-user.target"]; # 부팅 때 한 번 떠서 제어 파일이 켜져 있으면 이어서 수집, 꺼져 있으면 15초 뒤 종료
      restartIfChanged = false;
      environment.OBSERVE_IW = "${pkgs.iw}/bin/iw";
      environment.OBSERVE_BPFTRACE = "${pkgs.bpftrace}/bin/bpftrace"; # `observectl bpf <프리셋>`(eBPF): 요청할 때만 N초 실행
      unitConfig.StartLimitIntervalSec = 0;
      serviceConfig = {
        Type = "simple";
        ExecStart = "${py}/bin/python3 ${dir}/observe_collector.py";
        Nice = 10;
        ProtectHome = true;
        PrivateTmp = true;
      };
    };

    systemd.paths.observe-collector = {
      description = "start observectl collector when control file changes or a request is queued";
      wantedBy = ["multi-user.target"];
      pathConfig = {
        PathChanged = "/var/lib/observe/control.json";
        DirectoryNotEmpty = "/var/lib/observe/requests";
        Unit = "observe-collector.service";
      };
    };
  };
})
