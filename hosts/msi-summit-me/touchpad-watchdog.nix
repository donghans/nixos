# 터치패드 I2C 컨트롤러 행(hang) 감시 및 자동 복구
#
# (배경) MSI Summit E13 의 ELAN0305 터치패드는 i2c_hid_acpi → i2c_designware (PCI 00:15.0,
#   intel-lpss) 경로로 동작하는데, 세션 도중 i2c_designware 컨트롤러가 "controller timed out"
#   을 매초 쏟아내며 고착되어 터치패드가 죽는 현상이 있음. 자동 복구가 없어 한번 걸리면 재부팅 전까지 먹통.
#
# (동작) 120초마다(2026-10-25: 30초→120초, 장부 #121) 커널 로그를 점검해 최근 윈도우에 타임아웃이 임계치 이상 쌓이면
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

  threshold = 8; # 직전 점검(~120초 전) 이후 신규 타임아웃이 이만큼 이상이면 '고착' 판정
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
      # storm(초당 수십 회)이면 점검 간격(120초)에 수천 건이 잡힌다.
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
        # 터치패드 ACPI ID 는 부팅마다 ELAN0305 / MSNB0001 로 갈린다(2026-11-04 확인) — 둘 다 인식
        if grep -qE "(ELAN0305|MSNB0001).*Touchpad" /proc/bus/input/devices 2>/dev/null; then
          echo "touchpad input node: PRESENT"
        else
          echo "touchpad input node: MISSING"
        fi
      ) >> "$incident" 2>&1 || true

      echo "$now" > "$STAMP" 2>/dev/null || true
      echo "touchpad-watchdog: recovered (count=$count) -> $incident"
    '';
  };

  # 부팅 직후 터치패드 상태 스냅샷 — 먹통이 되기 전에 미리 남겨 두어, 사용자가 재인식 등을 건드리기 전의 "원래 상태"를 알 수 있게 한다.
  # (2026-11-07: 부팅마다 ACPI ID 가 ELAN0305/MSNB0001 로 갈리고, ELAN0305 일 때만 재인식이 `pin 62 cannot be used as IRQ` 로 실패하는 것으로 의심됨 — 가설 검증용)
  snapshot = pkgs.writeShellApplication {
    name = "touchpad-boot-snapshot";
    runtimeInputs = [pkgs.systemd pkgs.coreutils pkgs.gnugrep pkgs.findutils];
    text = ''
      LOGDIR="/var/log/touchpad-watchdog"
      out="$LOGDIR/boot-$(date +%Y%m%d-%H%M%S).log"
      (
        set +e +o pipefail
        echo "==== boot snapshot @ $(date +%T) (uptime $(cut -d' ' -f1 /proc/uptime)s) ===="
        echo "kernel: $(uname -r)   bios: $(cat /sys/class/dmi/id/bios_version 2>/dev/null) $(cat /sys/class/dmi/id/bios_date 2>/dev/null)"
        echo "cmdline: $(cat /proc/cmdline)"
        echo "--- 터치패드 ACPI ID / 상태 ---"
        found=0
        for d in /sys/bus/i2c/devices/i2c-ELAN0305:* /sys/bus/i2c/devices/i2c-MSNB0001:*; do
          [ -e "$d" ] || continue
          found=1
          echo "id: $(basename "$d")"
          echo "  acpi path: $(cat "$d/firmware_node/path" 2>/dev/null)"
          echo "  power_state: $(cat "$d/firmware_node/power_state" 2>/dev/null)"
          echo "  runtime_status: $(cat "$d/power/runtime_status" 2>/dev/null)"
          echo "  driver: $(readlink -f "$d/driver" 2>/dev/null)"
          echo "  irq: $(cat "$d/irq" 2>/dev/null)"
        done
        [ "$found" = 0 ] && echo "(ELAN0305/MSNB0001 i2c 장치 없음)"
        echo "touchpad input node: $(grep -cE '(ELAN0305|MSNB0001).*Touchpad' /proc/bus/input/devices)"
        echo "--- PCI 00:15.0 (LPSS I2C) ---"
        echo "power/control=$(cat /sys/bus/pci/devices/0000:00:15.0/power/control 2>/dev/null) runtime_status=$(cat /sys/bus/pci/devices/0000:00:15.0/power/runtime_status 2>/dev/null)"
        echo "--- 핀 62 (pinctrl INTC1055:00) ---"
        grep -E "^pin 62 " /sys/kernel/debug/pinctrl/INTC1055:00/pins 2>&1
        echo "--- 커널 로그 (이번 부팅, i2c/hid/pin/irq) ---"
        journalctl -k -b --no-pager 2>/dev/null \
          | grep -iE "i2c_hid|i2c_designware|intel-lpss|ELAN0305|MSNB0001|tigerlake-pinctrl|genirq" | tail -40
        echo "--- /proc/interrupts (i2c) ---"; grep -iE "i2c|ELAN|MSNB" /proc/interrupts
      ) > "$out" 2>&1 || true
      # 오래된 스냅샷 정리(최근 60개만 유지)
      find "$LOGDIR" -maxdepth 1 -name 'boot-*.log' -printf '%T@ %p\n' 2>/dev/null | sort -rn | tail -n +61 | cut -d' ' -f2- | xargs -r rm -f
      echo "touchpad-boot-snapshot: $out"
    '';
  };

  # 부팅 직후 첫 probe 가 `failed to fetch HID descriptor: -121`(장치가 아직 응답 안 함)로 실패하면 이후 재시도가 없어 터치패드가 안 잡힌다.
  # 같은 장치에 늦게 bind 하면 성공하는 것을 2026-11-07 에 확인(MSNB0001) → 입력 노드가 없으면 bind 를 재시도한다.
  # ELAN0305 로 뜬 부팅은 ACPI 가 IRQ 를 핀 62(DDSP_HPD_2, LOCKED)로 잡아 bind 가 `pin 62 cannot be used as IRQ` 로 실패(가설) → 재시도해도 소용없으니 멈추고 알린다.
  retry = pkgs.writeShellApplication {
    name = "touchpad-boot-retry";
    runtimeInputs = [pkgs.systemd pkgs.coreutils pkgs.gnugrep pkgs.libnotify pkgs.util-linux];
    text = ''
      LOGDIR="/var/log/touchpad-watchdog"
      log="$LOGDIR/retry-$(date +%Y%m%d-%H%M%S).log"
      drv=/sys/bus/i2c/drivers/i2c_hid_acpi
      has_node() { grep -qE '(ELAN0305|MSNB0001).*Touchpad' /proc/bus/input/devices; }
      say() { echo "[$(date +%T)] $*" >> "$log"; }
      notify() { # 로그인한 사용자 세션에 알림(실패해도 무시)
        runuser -u donghans -- env DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus \
          notify-send -u critical "터치패드" "$1" >/dev/null 2>&1 || true
      }

      if has_node; then exit 0; fi # 정상 — 로그도 남기지 않음

      shopt -s nullglob
      devs=()
      for p in /sys/bus/i2c/devices/i2c-ELAN0305:* /sys/bus/i2c/devices/i2c-MSNB0001:*; do devs+=("$(basename "$p")"); done
      say "터치패드 입력 노드 없음. i2c 장치: ''${devs[*]:-없음}"
      if [ "''${#devs[@]}" -eq 0 ]; then say "i2c 장치 자체가 없음 — 재시도 불가"; exit 1; fi

      for attempt in 1 2 3; do
        start_ts=$(date '+%Y-%m-%d %H:%M:%S')
        for dev in "''${devs[@]}"; do
          if [ -e "$drv/$dev" ]; then echo "$dev" > "$drv/unbind" 2>>"$log" || true; fi
          if echo "$dev" > "$drv/bind" 2>>"$log"; then say "시도 $attempt: bind $dev 성공"; else say "시도 $attempt: bind $dev 실패"; fi
        done
        sleep 3
        if has_node; then
          say "복구됨 (시도 $attempt)"
          notify "부팅 직후 인식 실패 → 자동 재시도로 복구됨 (''${devs[*]})"
          exit 0
        fi
        klog=$(journalctl -k --no-pager --since "$start_ts" | grep -iE 'cannot be used as IRQ|i2c_hid|genirq' | tail -5)
        say "커널 로그: $klog"
        if echo "$klog" | grep -q 'cannot be used as IRQ'; then
          say "핀 62 IRQ 오류 — ELAN0305 ACPI 변종 가설. 재시도 중단(재부팅하면 ID 가 바뀔 수 있음)"
          notify "터치패드 인식 실패(ELAN0305, IRQ 핀 오류). 재부팅/전원 껐다 켜기 필요"
          exit 1
        fi
        sleep 10
      done
      say "3회 재시도 후에도 실패"
      notify "터치패드 자동 복구 실패 — /var/log/touchpad-watchdog 참고"
      exit 1
    '';
  };
in {
  systemd.services.touchpad-boot-retry = {
    description = "Retry touchpad bind if boot-time probe failed (-121)";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${retry}/bin/touchpad-boot-retry";
      LogsDirectory = "touchpad-watchdog";
    };
  };
  systemd.timers.touchpad-boot-retry = {
    description = "Touchpad bind retry once, 30s after boot";
    wantedBy = ["timers.target"];
    timerConfig.OnBootSec = "30s"; # 부팅당 1회 — 주기 타이머 아님(전력 영향 없음), 부팅 완료를 막지도 않음
  };

  systemd.services.touchpad-boot-snapshot = {
    description = "Touchpad state snapshot after boot (ELAN0305/MSNB0001 diagnosis)";
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${snapshot}/bin/touchpad-boot-snapshot";
      LogsDirectory = "touchpad-watchdog";
    };
  };
  systemd.timers.touchpad-boot-snapshot = {
    description = "Touchpad snapshot once, 90s after boot";
    wantedBy = ["timers.target"];
    timerConfig.OnBootSec = "90s"; # 주기 타이머 아님(부팅당 1회) — 쉬는 전력 영향 없음
  };

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
    description = "Run touchpad watchdog every 120s";
    wantedBy = ["timers.target"];
    timerConfig = {
      OnBootSec = "60s";
      OnUnitActiveSec = "120s"; # 30초 → 120초: 켜 둔 주기 타이머 2개가 쉬는 전력을 약 +0.26 W 올림(장부 #121). 고착 감지가 최대 약 90초 늦어질 뿐
      AccuracySec = "30s"; # 다른 깨움과 묶일 여지
    };
  };
}
