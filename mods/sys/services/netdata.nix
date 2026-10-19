# Netdata — 시스템 지표(CPU/메모리/디스크/네트워크/프로세스…)를 기록해서 "그때 어땠는지"를 나중에 볼 수 있게 한다.
#  - 로컬에서만 열림(127.0.0.1:19999). nixpkgs 빌드에는 웹 대시보드 화면이 없어(withCloudUi=false, `/` 는 404) REST API(/api/v1/data 등)만 쓸 수 있음.
#    그래서 `power-report` 명령(전력/배터리/CPU 그래프 PNG + 요약)을 같이 설치하고, Claude 도 같은 API 로 구간 조회를 할 수 있음.
#  - 전원 정책(노트북): AC 연결 시 1초 간격, 배터리일 땐 10초 간격으로 수집(완전히 끄지 않는 이유: 배터리에서 TLP 상한으로
#    느려진 때의 기록이 오히려 쓸모 있음). 수집 주기는 서비스 시작 때 정해지므로 전원 상태가 바뀌면 udev 가 서비스를 재시작함(몇 초 공백).
#  - 익명 통계 전송은 모듈 기본값으로 꺼져 있고(DO_NOT_TRACK, .opt-out-from-anonymous-statistics), 클라우드 연결(claim)은 안 함.
#  - 부하를 줄이려고 머신러닝(이상 탐지), 알람(health), freeipmi 플러그인(서버용 센서, 노트북엔 대상 없음)은 끔. 보존: 초 단위 7일(최대 1GiB), 더 거친 단계(분/시간 단위)는 기본값.
{mkMod, ...}:
mkMod __curPos "Netdata (시스템 지표 기록: AC 1초 / 배터리 10초)" ({
  config,
  lib,
  pkgs,
  ...
}: let
  nd = config.services.netdata;
  acEvery = 1;
  batteryEvery = 10;

  # 시작 때 전원 상태를 읽어 /run/netdata/netdata.conf 를 만든다 ("@EVERY@" 자리를 주기로 바꿈).
  # Mains(전원 어댑터)가 하나라도 online 이면 AC, Mains 가 있는데 모두 offline 이면 배터리, Mains 가 없으면(데스크탑 등) AC.
  # SYSFS 로 경로를 바꿔 시험할 수 있음.
  genConf = pkgs.writeShellScript "netdata-genconf" ''
    ac=1
    for d in "''${SYSFS:-/sys/class/power_supply}"/*; do
      [ "$(cat "$d/type" 2>/dev/null)" = Mains ] || continue
      ac=0
      [ "$(cat "$d/online" 2>/dev/null)" = 1 ] && { ac=1; break; }
    done
    if [ "$ac" = 1 ]; then every=${toString acEvery}; else every=${toString batteryEvery}; fi
    ${pkgs.gnused}/bin/sed "s/@EVERY@/$every/" /etc/netdata/netdata.conf > "''${OUT:-/run/netdata/netdata.conf}"
  '';
  # 전원 상태를 Netdata(statsd, 127.0.0.1:8125)에 게이지로 기록: Netdata 가 기본으로는 충전/방전·AC 연결·TLP 모드를 남기지 않아서.
  #   power.ac_online (0/1), power.battery_state (0 방전, 1 충전, 2 완충, 3 충전 안 함, -1 알 수 없음),
  #   power.tlp_profile (/run/tlp/last_pwr 의 첫 값: TLP 가 마지막으로 적용한 전원 모드. 0 = AC, 1 = 배터리)
  # 값이 바뀔 때만이 아니라 주기적으로 다시 보내서, Netdata 가 재시작(전원 변경 시 udev 가 재시작함)돼도 몇 초 안에 복구됨.
  powerState = pkgs.writeShellScript "netdata-power-state" ''
    bat=""
    for d in /sys/class/power_supply/*; do
      [ "$(cat "$d/type" 2>/dev/null)" = Battery ] && { bat=$d; break; }
    done
    while :; do
      ac=0
      for d in /sys/class/power_supply/*; do
        [ "$(cat "$d/type" 2>/dev/null)" = Mains ] && [ "$(cat "$d/online" 2>/dev/null)" = 1 ] && ac=1
      done
      case "$(cat "$bat/status" 2>/dev/null)" in
        Discharging) b=0 ;; Charging) b=1 ;; Full) b=2 ;; "Not charging") b=3 ;; *) b=-1 ;;
      esac
      tlp=-1
      read -r tlp _ < /run/tlp/last_pwr 2>/dev/null || tlp=-1
      printf 'power.ac_online:%s|g\npower.battery_state:%s|g\npower.tlp_profile:%s|g\n' "$ac" "$b" "$tlp" > /dev/udp/127.0.0.1/8125 2>/dev/null
      sleep 10
    done
  '';

  # Netdata API 로 배터리 잔량/전력(RAPL, 전압×전류)/CPU 를 같은 시간축 그래프와 요약으로 보여주는 도구 (스크립트: _data/netdata/power_report.py)
  powerReport = pkgs.writeShellScriptBin "power-report" ''
    exec ${pkgs.python3.withPackages (p: [p.matplotlib])}/bin/python3 ${../../_data/netdata/power_report.py} "$@"
  '';
  # 어댑터를 뽑은 상태에서 화면 주사율별 소비 전력을 번갈아 재서 비교(스크립트: _data/power-ab/power_ab.py)
  powerAb = pkgs.writeShellScriptBin "power-ab" ''
    # displayctl 은 사용자 프로필(~/.nix-profile/bin)에 있어서 PATH 를 덧붙임
    export PATH=${lib.makeBinPath [pkgs.hyprland]}:$HOME/.nix-profile/bin:$PATH
    exec ${pkgs.python3}/bin/python3 ${../../_data/power-ab/power_ab.py} "$@"
  '';
in {
  hm.home.packages = [powerReport powerAb];

  os = {
    services.netdata = {
      enable = true;
      config = {
        db = {
          mode = "dbengine";
          "update every" = "@EVERY@";
          "dbengine tier 0 retention time" = "7d";
          "dbengine tier 0 retention size" = "1GiB";
        };
        web."bind to" = "localhost";
        ml.enabled = "no";
        health.enabled = "no";
        # freeipmi: 서버 메인보드(BMC)의 센서를 읽는 플러그인. 노트북에는 대상이 없는데도 계속 찾느라 CPU 를 약 38%(코어 1개 기준) 썼음(실측).
        plugins.freeipmi = "no";
      };
    };

    systemd.services.netdata.serviceConfig = {
      ExecStartPre = "${genConf}";
      ExecStart = lib.mkForce "${nd.package}/bin/netdata -P /run/netdata/netdata.pid -D -c /run/netdata/netdata.conf";
    };

    systemd.services.netdata-power-state = {
      # (부팅 콘솔(가상 콘솔)은 한글 글리프가 없어 네모로 보이므로 시스템 유닛 Description 은 영어로: 전원 상태(AC/충전/TLP 모드)를 Netdata 에 기록)
      description = "Record power state (AC/charging/TLP mode) for Netdata";
      after = ["netdata.service"];
      wantedBy = ["multi-user.target"];
      serviceConfig = {
        ExecStart = "${powerState}";
        DynamicUser = true;
        Restart = "on-failure";
        # 읽기만 하는 아주 작은 루프라서 권한 최소화
        ProtectSystem = "strict";
        ProtectHome = true;
        PrivateTmp = true;
        NoNewPrivileges = true;
      };
    };

    # 전원 어댑터를 꽂거나 뽑으면 수집 주기를 다시 정하도록 재시작 (실행 중일 때만)
    services.udev.extraRules = ''
      SUBSYSTEM=="power_supply", ACTION=="change", ATTR{type}=="Mains", RUN+="${pkgs.systemd}/bin/systemctl --no-block try-restart netdata.service"
    '';
  };
})
