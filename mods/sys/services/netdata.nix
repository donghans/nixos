# Netdata — 시스템 지표(CPU/메모리/디스크/네트워크/프로세스…)를 기록해서 "그때 어땠는지"를 나중에 볼 수 있게 한다.
#  - 웹 화면: http://localhost:19999 (로컬에서만 열림). 같은 주소의 REST API(/api/v1/data 등)로 Claude 도 구간 조회를 할 수 있음.
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
in {
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

    # 전원 어댑터를 꽂거나 뽑으면 수집 주기를 다시 정하도록 재시작 (실행 중일 때만)
    services.udev.extraRules = ''
      SUBSYSTEM=="power_supply", ACTION=="change", ATTR{type}=="Mains", RUN+="${pkgs.systemd}/bin/systemctl --no-block try-restart netdata.service"
    '';
  };
})
