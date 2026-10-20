# observectl / observe — 관측 시스템: 전력/프로세스/C-state 수집기(root), 우리 유틸리티의 구조화 이벤트 로그, 프로파일·타임라인·A/B 통계 CLI
#  - 본체는 mods/_data/observe/ (설명은 파일 머리말과 _docs/content/explanation/observectl.md).
#  - 켜고 끄기: `observectl on [L0|L1]` / `observectl off` — 제어 파일(/var/lib/observe/control.json, 그룹 users 쓰기 가능)만 바꾼다.
#    수집기는 systemd **path 유닛**이 제어 파일 변경/요청 디렉터리에 파일이 생길 때만 띄우고, 꺼져 있고 할 일이 없으면 15초 뒤 스스로 종료한다
#    (꺼져 있는 동안 프로세스가 없으므로 측정에 영향을 주지 않는다. 켜져 있을 때의 오버헤드는 `observectl ab` 로 직접 재서 power-evidence.md 에 기록).
#  - 개인정보: 프로세스는 comm 과 exe 이름만, 명령 인자·URL·입력한 글자는 기록하지 않는다.
#  - Netdata(1초/10초 간격 시스템 지표, 7일)는 그대로 둔다. observectl 는 Netdata 가 못 보는 것(스레드·깨움 원인·패키지 C-state·유틸리티 이벤트·실험 표지)을 맡는다.
{mkMod, ...}:
mkMod __curPos "observectl (관측: 수집기 · 이벤트 로그 · 프로파일/타임라인/A-B CLI)" ({
  lib,
  pkgs,
  ...
}: let
  py = pkgs.python3;
  dir = pkgs.runCommand "observe-src" {} ''
    mkdir -p $out
    ${lib.concatMapStringsSep "\n" (f: "cp ${../../_data/observe + "/${f}"} $out/${f}") ["observe_core.py" "observe_events.py" "observe_stats.py" "observe_collector.py" "observe_cli.py" "observe_emit.py"]}
  '';
  observectl = pkgs.writeShellScriptBin "observectl" ''exec ${py}/bin/python3 ${dir}/observe_cli.py "$@"'';
  observeEmit = pkgs.writeShellScriptBin "observe-emit" ''exec ${py}/bin/python3 ${dir}/observe_emit.py "$@"'';
in {
  os = {
    environment.systemPackages = [observectl observeEmit];

    # MSR(패키지 C-state 잔여율)을 읽으려면 msr 모듈이 필요(root 만 접근). 수집기가 없을 때 modprobe 도 시도하지만 부팅 때 올려 둔다.
    boot.kernelModules = ["msr"];

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
