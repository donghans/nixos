#!/usr/bin/env python3
"""power-ab 시험: sysfs 읽기/와트 계산/CPU 사용률/요약/표시, 방전이 아닐 때 거부."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
from harness import checker, tmpdir
check, finish = checker()
d = tmpdir()
os.makedirs(f"{d}/BAT1"); os.makedirs(f"{d}/ADP1")
def put(rel, val): open(f"{d}/{rel}", "w").write(str(val) + "\n")
for k, v in {"status": "Discharging", "voltage_now": 15_000_000, "current_now": 800_000, "charge_full": 3_615_000}.items(): put(f"BAT1/{k}", v)
put("stat", "cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 1 1 1 1")
os.environ["POWER_AB_SYSFS"] = d; os.environ["POWER_AB_PROC_STAT"] = f"{d}/stat"
import power_ab as p
check("배터리 디렉터리 찾기(BAT*)", p.battery(d) == f"{d}/BAT1")
w, st = p.watts(f"{d}/BAT1")
check("소비 전력 = 전압(µV) × 전류(µA): 15V × 0.8A = 12W", abs(w - 12.0) < 1e-9 and st == "Discharging", str(w))
put("BAT1/current_now", -800_000)
check("전류 부호가 음수여도 크기로 계산", abs(p.watts(f"{d}/BAT1")[0] - 12.0) < 1e-9)
check("전압/전류 파일이 없으면 None", p.watts(f"{d}/ADP1")[0] is None)
a, b = (1000, 800), (1100, 880)
check("CPU 사용률: 전체 +100 중 유휴 +80 → 20%", abs(p.cpu_busy(a, b) - 20.0) < 1e-9)
check("CPU 사용률: 변화가 없으면 0", p.cpu_busy(a, a) == 0.0)
check("/proc/stat 첫 줄에서 전체/유휴(idle+iowait) 계산", p.cpu_times(f"{d}/stat") == (1000, 800), str(p.cpu_times(f"{d}/stat")))
s = p.summarize([{"w": 10.0, "cpu": 2.0}, {"w": 12.0, "cpu": 4.0}, {"w": 11.0, "cpu": 3.0}])
check("요약: 중앙값/평균/최소/최대/CPU 평균", s["median"] == 11.0 and s["mean"] == 11.0 and s["min"] == 10.0 and s["max"] == 12.0 and s["cpu"] == 3.0, str(s))
check("배터리 Wh = 만충 용량(Ah) × 15.2V", abs(p.battery_wh(f"{d}/BAT1") - 3.615 * 15.2) < 1e-6)
check("사용 시간 = Wh / W (0W 면 0)", abs(p.hours(54.0, 6.0) - 9.0) < 1e-9 and p.hours(54.0, 0) == 0.0)
r = p.render({"165": [{"median": 8.0, "cpu": 2.0}, {"median": 8.2, "cpu": 2.0}], "60": [{"median": 7.0, "cpu": 2.0}, {"median": 7.1, "cpu": 20.0}]}, 55.0)
check("표: 기준(첫 설정) 대비 차이와 바퀴 간 차이, CPU 바쁨 경고", "-1.05 W" in r and "0.20 W" in r and "CPU 바쁨" in r and "165" in r, r)
put("BAT1/status", "Full")
import io, contextlib
err = io.StringIO()
with contextlib.redirect_stderr(err): rc = p.main([])
check("어댑터가 연결돼(방전이 아니면) 거부하고 안내", rc == 2 and "뽑" in err.getvalue(), err.getvalue())
finish("power-ab")
