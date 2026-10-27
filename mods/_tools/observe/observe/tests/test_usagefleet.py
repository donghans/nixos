#!/usr/bin/env python3
"""usagefleet 시험: 전력 계열 선택(psys 우선·없으면 패키지), 그래프, 앱 비교 표, 확장 차이 표, 받기(성공→캐시, 실패→낡은 값+사유, 둘 다 없음)."""
import json, os, stat, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="usagefleet-test-")
os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var"); os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
import usagefleet as uf
check, finish = checker()

NOW = int(time.time())
H = [NOW - 3600 * i for i in range(48, 0, -1)]
DATA = {"version": 1, "fetched": NOW, "days": 3, "me": "nb", "hosts": ["dt", "nb"],
        "power": {"nb": [[t, 2.0 + (i % 3) * 0.1, 1.0, 100] for i, t in enumerate(H)], "dt": [[t, None, 20.0 + i % 2, 100] for i, t in enumerate(H)]},
        "means": {"nb": {"vivaldi-bin": [0.6, 10.0], "tailscaled": [0.5, 40.0], "node": [21.0, 100.0], "python3": [0.5, 2.0]},
                  "dt": {"vivaldi-bin": [0.05, 5.0], "node": [22.0, 100.0], "python3": [0.4, 2.0]}},
        "samples": {"nb": 8000, "dt": 8100},
        "inventory_diff": [["nb", "vivaldi", "a" * 32, "Default", "1.0", True], ["nb", "vivaldi", "b" * 32, "Default,Profile 1", "2.0", False]]}

pts, unit, kind = uf.series(DATA, "nb")
check("series: psys 가 있으면 psys 를 쓴다", kind == "psys" and len(pts) == 48 and unit == "W")
pts2, _, kind2 = uf.series(DATA, "dt")
check("series: psys 가 없는 호스트는 패키지(CPU+GPU)로 대체", kind2 == "패키지" and pts2[0][1] in (20.0, 21.0))
check("series: 없는 호스트는 빈 점", uf.series(DATA, "x")[0] == [])
t, sub = uf.power_chart(DATA, "nb", 60, 8)
check("power_chart: 그래프 본문 8줄과 부제(호스트·지표 포함)", len(t.plain.splitlines()) == 8 and sub.startswith("nb · psys · "), sub)
t2, sub2 = uf.power_chart(DATA, "ghost", 60, 8)
check("power_chart: 값이 없으면 안내 문장", "올라와 있지 않습니다" in t2.plain and sub2 == "")
rows = uf.compare_rows(DATA, "nb", "dt")
check("compare_rows: 3배↑ vivaldi 와 한쪽에만 있는 tailscaled, 비슷한 node·작은 차이 python3 제외", [r[0] for r in rows] == ["vivaldi-bin", "tailscaled"] and rows[1][3] == "한쪽에만 있음" and rows[0][3] == "3배↑", str(rows))
check("compare_rows: 반대로 보면(dt 기준) 높은 앱 없음", uf.compare_rows(DATA, "dt", "nb") == [])
inv = uf.inventory_rows(DATA)
check("inventory_rows: 서비스 워커 표시(★)와 ID 줄임, 확장 이름 없음", inv[0][5].startswith("★") and inv[1][5] == "" and inv[0][2] == "a" * 16 + "…", str(inv))
check("others: 이 호스트를 뺀 목록", uf.others(DATA) == ["dt"])
st = uf.status_text(DATA, "낡음", "nb", "dt")
check("status_text: 호스트·표본 수·비교 대상·낡음 경고", "nb(표본 8,000개)" in st.plain and "nb ↔ dt" in st.plain and "낡음" in st.plain)
check("status_text: 데이터 없음이면 사유와 올리는 방법 안내", "y 키" in uf.status_text(None, "접속 실패", "nb", None).plain and "접속 실패" in uf.status_text(None, "접속 실패", "nb", None).plain)

# --- 받기: 가짜 observectl
BIN = os.path.join(TMP, "bin"); os.makedirs(BIN)
def fake(body):
    p = os.path.join(BIN, "observectl"); open(p, "w").write("#!/bin/sh\n" + body + "\n"); os.chmod(p, os.stat(p).st_mode | stat.S_IEXEC)
os.environ["PATH"] = BIN + os.pathsep + os.environ["PATH"]
check("load: observectl 이 없으면 (None, 사유)", uf.load() == (None, "observectl 이 없습니다") or uf.load()[0] is None)
fake("echo '" + json.dumps(DATA) + "'")
d, note = uf.load()
check("load: 성공이면 데이터·안내 없음, 캐시 파일 생성", d and d["me"] == "nb" and note is None and os.path.exists(uf.cache_path()))
fake("echo '공유 저장소 접속 실패: x' >&2; exit 1")
d2, note2 = uf.load()
check("load: 실패하면 마지막으로 받은 값(캐시)과 낡음·사유를 돌려줌", d2 and d2["me"] == "nb" and note2 and "접속 실패" in note2 and "받은 값을 보임" in note2, str(note2))
os.remove(uf.cache_path())
d3, note3 = uf.load()
check("load: 캐시도 없으면 (None, 사유)", d3 is None and "접속 실패" in note3, str(note3))
finish("usagefleet")
