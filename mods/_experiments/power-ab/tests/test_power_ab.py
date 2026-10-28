#!/usr/bin/env python3
"""power-ab 시험: sysfs 읽기/와트 계산/CPU 사용률/요약/표시, 방전이 아닐 때 거부."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "..", "_tools", "_lib", "testkit"))
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
pts = [p.circle_point(100, 100, 50, 4.0, t) for t in (0, 1, 2, 3)]
check("원 둘레 점: 한 바퀴 4초, 1초마다 90도(오른쪽→아래→왼쪽→위)", pts == [(150, 100), (100, 150), (50, 100), (100, 50)], str(pts))
check("원 둘레 점: 한 바퀴 뒤에는 제자리", p.circle_point(100, 100, 50, 4.0, 4.0) == p.circle_point(100, 100, 50, 4.0, 0.0))
check("Hyprland 커서 이동 명령 형식(Lua)", p.cursor_cmd(12, 34) == "dispatch hl.dsp.cursor.move({ x = 12, y = 34 })")
# Netdata RAPL 조회(가짜 응답)
import io, json as _json
class Resp(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): return False
urls = []
def fake_open(url, timeout=0):
    urls.append(url)
    return Resp(_json.dumps({"data": [[1700000000, 3.0, 1.5]]}).encode())
check("Netdata: 구간 평균(여러 차원은 합산)과 요청 인자", p.netdata_avg("cpu.x", 100.4, 200.9, fake_open) == 4.5 and "after=100" in urls[0] and "before=200" in urls[0] and "points=1" in urls[0] and "group=average" in urls[0], str(urls))
def bad_open(url, timeout=0): raise OSError("down")
check("Netdata: 연결 실패/빈 데이터는 None", p.netdata_avg("c", 0, 1, bad_open) is None and p.netdata_avg("c", 0, 1, lambda u, timeout=0: Resp(b'{"data": []}')) is None)
check("with_rapl: 요약에 pkg/psys 를 붙임", p.with_rapl({"median": 1.0}, {"pkg": 3.0, "psys": 9.0}) == {"median": 1.0, "pkg": 3.0, "psys": 9.0})

# 컨테이너 일시정지(가짜 docker)
state = {"running": ["genple", "redis", "db"], "calls": []}
class RR:  # noqa
    def __init__(self, rc=0, out=""): self.returncode, self.stdout = rc, out
def fake_docker(*a):
    state["calls"].append(a)
    return RR(0, "\n".join(state["running"])) if a[0] == "ps" else RR(0 if a[1] != "bad" else 1)
p.docker = fake_docker
p.paused.clear()
check("c-genple: genple 만 pause", p.apply("c-genple") and p.paused == {"genple"} and ("pause", "genple") in state["calls"])
state["calls"].clear()
check("c-all: 나머지도 pause(이미 멈춘 genple 은 다시 pause 안 함)", p.apply("c-all") and p.paused == {"genple", "redis", "db"} and ("pause", "genple") not in state["calls"], str(state["calls"]))
state["calls"].clear()
check("c-run: 우리가 멈춘 것을 모두 unpause", p.apply("c-run") and p.paused == set() and {("unpause", "genple"), ("unpause", "redis"), ("unpause", "db")} <= set(state["calls"]), str(state["calls"]))
check("알 수 없는 컨테이너 시나리오/숫자 아닌 이름은 거부", p.apply("c-nothing") is False and p.apply("abc") is False)
p.CONTAINER_FOCUS = "bad"
check("pause 가 실패하면 False(멈췄다고 기록하지 않음)", p.apply("c-genple") is False and p.paused == set())

# 표시: psys/패키지 열
rr = p.render({"c-run": [{"median": 12.0, "cpu": 15.0, "pkg": 6.0, "psys": 12.5}, {"median": 12.2, "cpu": 15.0, "pkg": 6.2, "psys": 12.7}],
               "c-all": [{"median": 9.9, "cpu": 3.0, "pkg": 3.5, "psys": 10.3}, {"median": 10.1, "cpu": 3.0, "pkg": 3.7, "psys": 10.5}]}, 55.0)
check("표: 소비전력 −2.10, psys −2.20, 패키지 −2.50 의 기준 대비와 안내", "-2.10 W" in rr and "-2.20 W" in rr and "-2.50 W" in rr and "psys" in rr and "믿을 수 있다" in rr and "CPU 바쁨" not in rr, rr)
rr2 = p.render({"60": [{"median": 10.0, "cpu": 15.0}], "48": [{"median": 9.8, "cpu": 15.0}]}, 55.0)
check("표: Netdata 값이 없으면 열 없이(CPU 바쁨 경고 유지)", "psys" not in rr2 and "CPU 바쁨" in rr2)
finish("power-ab")
