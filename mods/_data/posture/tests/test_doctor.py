#!/usr/bin/env python3
"""posture-doctor 시험: 가짜 systemctl/hyprctl/journalctl 과 임시 디렉터리로 각 고장 상황을 재현해 올바른 등급이 나오는지 확인."""
import json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
from harness import checker
from fakes import Sandbox
check, finish = checker()

class World:
    """가짜 시스템: 공용 Sandbox(가짜 systemctl/hyprctl/journalctl) + 파일 몇 개로 상태를 정함."""
    def __init__(self):
        self.sb = Sandbox(); self.d = self.sb.dir
        for sub in ("state", "run/hypr/SIG1", "bl/intel", "acpi"): os.makedirs(f"{self.d}/{sub}")
        os.symlink(f"{self.d}/run/hypr", f"{self.d}/hypr")      # 가짜 hyprctl -i <서명> 이 보는 FAKE_DIR/hypr/<서명> = 실제 런타임 디렉터리
        open(f"{self.d}/run/wayland-1", "w").close()
        self.write_state(lid="open")
        self.set_backlight(96000); open(f"{self.d}/acpi/state", "w").write("state:      open\n")
        self.daemon_active = True; self.env_sig = "SIG1"; self.env_wl = "wayland-1"; self.journal = "applied: laptop lid=open\n"
    def write_state(self, **kw):
        d = {"schema": 1, "ts": 1, "mode": "laptop", "orientation": {"rotation": 0, "flat": False}, "lid": "open", "sensors": {"hinge": "ok", "accel": "ok", "lid": "ok"}}; d.update(kw)
        json.dump(d, open(f"{self.d}/state/state.json", "w"))
    def set_backlight(self, v): open(f"{self.d}/bl/intel/actual_brightness", "w").write(str(v))
    def run(self):
        sb = self.sb
        sb.write("environment.txt", f"WAYLAND_DISPLAY={self.env_wl}\n" + (f"HYPRLAND_INSTANCE_SIGNATURE={self.env_sig}\n" if self.env_sig else ""))
        sb.write("active_units.txt", ("posture-daemon.service " if self.daemon_active else "") + "posture-apply.path\n")
        sb.write("journal.txt", self.journal)
        env = sb.env(POSTURE_STATE_DIR=f"{self.d}/state", DOCTOR_SYSTEMCTL=sb.path("systemctl"), DOCTOR_HYPRCTL=sb.path("hyprctl"), DOCTOR_JOURNALCTL=sb.path("journalctl"),
                     DOCTOR_RUNTIME_DIR=f"{self.d}/run", DOCTOR_BACKLIGHT_DIR=f"{self.d}/bl", DOCTOR_LID_STATE=f"{self.d}/acpi/state")
        r = subprocess.run([sys.executable, "-I", f"{ROOT}/doctor.py", "--json"], capture_output=True, text=True, env=env)
        return r.returncode, json.loads(r.stdout), r.stderr
def levels(rows): return {r["name"]: r["level"] for r in rows}
def has(rows, name_part, level): return any(name_part in r["name"] and r["level"] == level for r in rows)

w = World(); rc, rows, err = w.run()
check("정상: 종료 코드 0, FAIL/WARN 없음", rc == 0 and all(r["level"] == "OK" for r in rows) and len(rows) >= 7, str(levels(rows)) + err)

w = World(); w.daemon_active = False; rc, rows, _ = w.run()
check("데몬이 죽음: FAIL + 종료 코드 1", rc == 1 and has(rows, "허브 데몬", "FAIL"))

w = World(); w.env_sig = ""; rc, rows, _ = w.run()
check("서비스 환경에 HYPRLAND_INSTANCE_SIGNATURE 없음(중첩 Hyprland 오염): FAIL + 복구 힌트", rc == 1 and has(rows, "HYPRLAND_INSTANCE_SIGNATURE", "FAIL") and any("set-environment" in r["hint"] for r in rows))

w = World(); w.env_sig = "DEAD"; rc, rows, _ = w.run()
check("죽은 인스턴스를 가리키면 FAIL", has(rows, "HYPRLAND_INSTANCE_SIGNATURE", "FAIL"))

w = World(); w.env_wl = "wayland-2"; rc, rows, _ = w.run()
check("죽은 WAYLAND_DISPLAY(wayland-2 소켓 없음): FAIL", has(rows, "WAYLAND_DISPLAY", "FAIL"))

w = World(); w.journal = "applied: laptop\n소비자 실패: /nix/store/x-displayctl/bin/displayctl rotate auto\napplied: laptop\n"
rc, rows, _ = w.run()
check("마지막 패스에서 소비자 실패: WARN 에 소비자 이름", has(rows, "소비자 실행", "WARN") and any("displayctl rotate auto" in r["detail"] for r in rows), str(rows))

w = World(); w.journal = "소비자 실패: /nix/store/x-vkb/bin/vkb apply-posture\napplied: laptop\napplied: laptop\n"
rc, rows, _ = w.run()
check("실패가 마지막 패스 이전(이미 지나간 것)이면 OK", has(rows, "소비자 실행", "OK"), str(rows))

w = World(); w.set_backlight(0); rc, rows, _ = w.run()
check("덮개는 열렸는데 백라이트 0: FAIL + lid-screen on 힌트", rc == 1 and has(rows, "화면", "FAIL") and any("lid-screen on" in r["hint"] for r in rows))

w = World(); w.write_state(lid="closed"); w.set_backlight(0); open(f"{w.d}/acpi/state", "w").write("state:      closed\n"); rc, rows, _ = w.run()
check("덮개가 닫혀 있고 백라이트 0: 정상", rc == 0 and has(rows, "화면", "OK"), str(rows))

w = World(); w.write_state(lid="closed"); rc, rows, _ = w.run()
check("허브는 closed 인데 ACPI 는 open: FAIL(이벤트 유실)", rc == 1 and has(rows, "덮개 상태", "FAIL"))

w = World(); w.write_state(sensors={"hinge": "ok", "accel": "error", "lid": "ok"}); rc, rows, _ = w.run()
check("센서 읽기 오류: WARN", has(rows, "센서 accel", "WARN") and rc == 0)

finish("doctor")
