# 터치패드 I2C 컨트롤러 행(hang) 감시 및 자동 복구
#
# (배경) MSI Summit E13 의 ELAN0305 터치패드는 i2c_hid_acpi → i2c_designware (PCI 00:15.0,
#   intel-lpss) 경로로 동작하는데, 세션 도중 i2c_designware 컨트롤러가 "controller timed out"
#   을 매초 쏟아내며 고착되어 터치패드가 죽는 현상이 있음. 자동 복구가 없어 한번 걸리면 재부팅 전까지 먹통.
#
# (동작) 30초마다 커널 로그를 점검해 최근 윈도우에 타임아웃이 임계치 이상 쌓이면
#   ① 진단 로그를 /var/log/touchpad-watchdog/ 에 수집하고
#   ② intel-lpss 드라이버를 언바인드→리바인드 후 power/control=on 강제로 컨트롤러를 리셋.
#   (수동 복구로 검증된 절차와 동일)
#
# (주의) 대증요법임. 근본 원인은 hosts/msi-summit-me.nix 의 pci=nocrs 로 의심되며,
#   수집된 incident 로그로 그 파라미터 제거 효과를 검증하는 용도로도 사용.
{pkgs, ...}: let
  pciAddr = "0000:00:15.0";
  driverDir = "/sys/bus/pci/drivers/intel-lpss";
  powerCtl = "/sys/devices/pci0000:00/0000:00:15.0/power/control";
  runtimeStatus = "/sys/devices/pci0000:00/0000:00:15.0/power/runtime_status";

  threshold = 8; # 직전 점검(~30초 전) 이후 신규 타임아웃이 이만큼 이상이면 '고착' 판정
  cooldownSec = 180; # 직전 복구 후 이 시간(초) 안에는 재복구 안 함 (settle 대기 + 무한루프 방지)

  watchdog = pkgs.writeShellApplication {
    name = "touchpad-watchdog";
    runtimeInputs = [pkgs.systemd pkgs.coreutils pkgs.gnugrep];
    text = ''
      LOGDIR="/var/log/touchpad-watchdog"
      STAMP="/var/lib/touchpad-watchdog/last-recovery-epoch"
      CURSOR="/var/lib/touchpad-watchdog/cursor"

      # 최초 실행(커서 없음): 현재 위치에만 커서를 찍고 종료.
      # (-k 에서 --since 시각필터는 부팅 초기 NTP 보정 등으로 과거 storm 을 오탐하므로
      #  시각이 아닌 '저널 위치' 기준으로 신규 메시지만 판정한다.)
      if [ ! -f "$CURSOR" ]; then
        journalctl -k -n1 --cursor-file="$CURSOR" >/dev/null 2>&1 || true
        exit 0
      fi

      # 직전 실행 이후 새로 쌓인 커널 메시지만 읽으며 커서를 전진.
      # storm(초당 수십 회)이면 ~30초 간격에 수백 건이 잡힌다.
      count=$(journalctl -k --cursor-file="$CURSOR" --no-pager 2>/dev/null \
                | grep -c "i2c_designware.0: controller timed out" || true)
      [ "''${count:-0}" -lt ${toString threshold} ] && exit 0 # 정상

      now=$(date +%s)
      if [ -f "$STAMP" ]; then
        last=$(cat "$STAMP" 2>/dev/null || echo 0)
        [ $((now - last)) -lt ${toString cooldownSec} ] && exit 0 # 쿨다운 중
      fi

      ts=$(date +%Y%m%d-%H%M%S)
      incident="$LOGDIR/incident-$ts.log"

      # ── ① 진단 로그 수집 (근본 원인 분석용) ──
      # 서브셸로 격리하고 set -e/pipefail을 해제 — 진단 명령 하나가 실패해도
      # 블록이 중단되거나(버퍼 유실) 스크립트가 exit 1로 죽지 않도록 함.
      (
        set +e +o pipefail
        echo "==== incident @ $ts (new timeouts since last check = $count) ===="
        echo "--- uptime(sec) ---"; cat /proc/uptime
        echo "--- power/control ---"; cat ${powerCtl} 2>/dev/null
        echo "--- runtime_status ---"; cat ${runtimeStatus} 2>/dev/null
        echo "--- bound driver ---"; readlink -f /sys/bus/pci/devices/${pciAddr}/driver 2>/dev/null
        echo "--- kernel log (i2c/elan/hid, last 60) ---"
        journalctl -k --no-pager -n 400 2>/dev/null \
          | grep -iE "i2c_designware|i2c_hid|ELAN0305|intel-lpss|lost arbitration" | tail -60
        echo "--- /proc/interrupts (i2c) ---"; grep -iE "i2c|ELAN|designware" /proc/interrupts
      ) > "$incident" 2>&1 || true

      # ── ② 복구: intel-lpss 언바인드→리바인드 후 전원 강제 ──
      echo "[recover] unbind/rebind ${pciAddr}" >> "$incident"
      echo "${pciAddr}" > "${driverDir}/unbind" 2>>"$incident" || true
      sleep 1
      echo "${pciAddr}" > "${driverDir}/bind"   2>>"$incident" || true
      sleep 2
      echo on > ${powerCtl} 2>>"$incident" || true
      sleep 3

      # ── 결과 검증 기록 ──
      (
        set +e +o pipefail
        echo "--- after recovery ---"
        echo "power/control: $(cat ${powerCtl} 2>/dev/null || echo n/a)"
        echo "runtime_status: $(cat ${runtimeStatus} 2>/dev/null || echo n/a)"
        if grep -q "ELAN0305.*Touchpad" /proc/bus/input/devices 2>/dev/null; then
          echo "touchpad input node: PRESENT"
        else
          echo "touchpad input node: MISSING"
        fi
      ) >> "$incident" 2>&1 || true

      echo "$now" > "$STAMP" 2>/dev/null || true
      echo "touchpad-watchdog: recovered (count=$count) -> $incident"
    '';
  };
in {
  systemd.services.touchpad-watchdog = {
    description = "ELAN touchpad I2C controller hang watchdog + auto-recovery";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${watchdog}/bin/touchpad-watchdog";
      LogsDirectory = "touchpad-watchdog"; # /var/log/touchpad-watchdog
      StateDirectory = "touchpad-watchdog"; # /var/lib/touchpad-watchdog (쿨다운 스탬프 영속)
    };
  };

  systemd.timers.touchpad-watchdog = {
    description = "Run touchpad watchdog every 30s";
    wantedBy = ["timers.target"];
    timerConfig = {
      OnBootSec = "60s";
      OnUnitActiveSec = "30s";
      AccuracySec = "5s";
    };
  };
}
