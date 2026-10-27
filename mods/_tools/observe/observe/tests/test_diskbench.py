#!/usr/bin/env python3
"""diskbench 시험: 임시 파일 벤치마크(tmpfs 에서는 O_DIRECT 불가 → 대체 경로), 거부 조건, 기록 저장·로드, usagelive 가 실측을 분모 1순위로 쓰는지."""
import os, sys, tempfile, time, json
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="diskbench-test-")
os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state"); os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "_testkit")); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "..", "..", "_data", "claude-skills", "donghans-host-resources", "scripts"))
import diskbench as db
from harness import checker
check, finish = checker()

d = os.path.join(TMP, "bench")
r = db.bench_file(d, 8)
check("bench_file: 읽기·쓰기 속도(바이트/초)와 크기, 임시 파일은 지워짐", r.get("read", 0) > 0 and r.get("write", 0) > 0 and r["size"] == 8 << 20 and not [f for f in os.listdir(d) if f.endswith(".tmp")], str(r))
check("bench_file: direct 여부가 기록됨(tmpfs 는 False 일 수 있음)", isinstance(r["direct"], bool))
check("bench_file: 쓸 수 없는 디렉터리는 error 문구(예외 아님)", "error" in db.bench_file("/proc/nope", 1))
res = db.run(8, directory=d)
check("run: 임시 파일이 tmpfs/가상 장치면 디스크를 알 수 없다고 거부하거나, 실제 디스크면 결과를 돌려줌", ("error" in res and "디스크" in res["error"]) or all("read" in v for v in res.values()), str(res))
home = os.path.expanduser("~")
check("whole_disks: 홈이 놓인 곳은 전체 디스크 이름(파티션·dm 은 부모로)", all(not n.startswith(("loop", "zram")) and "p" not in n[-3:] or n.startswith("nvme") for n in db.whole_disks(home)), str(db.whole_disks(home)))
check("whole_disks: 존재하지 않는 경로·tmpfs 는 빈 집합", db.whole_disks("/nonexistent-zzz") == set())
db.save({"nvmeX": dict(read=2e9, write=1e9, at=time.time(), direct=True, size=1 << 30)})
check("save/load: 상태 파일 왕복", db.load()["nvmeX"]["read"] == 2e9 and oct(os.stat(db.state_path()).st_mode & 0o777))
# 거부: 여유 공간 부족
big = db.run(10 ** 9, directory=d)
check("run: 여유 공간이 모자라면 크기를 밝히며 거부(디스크에 쓰지 않음)", "error" in big and "여유 공간" in big["error"], str(big))
import usagelive as lv
info = lv.disk_info()
check("disk_info: 기록이 있는 장치만 bench 가 붙음", all((v["bench"] is None) == (k != "nvmeX") for k, v in info.items()))
fake = dict(info={}, )
from rich.text import Text
s1 = dict(cores=[1.0], cpu=dict(count=1, busy_pct=1.0, load=(0.1, 0.1, 0.1)), net={}, links={}, disk={"nvmeX": (1e9, 5e8)},
          disk_info={"nvmeX": dict(model="X", name=None, read=7e9, write=5e9, link=7.88e9, bench=dict(read=2e9, write=1e9, at=time.time()))})
txt = lv.render_io(s1, 70).plain
check("render: 실측이 있으면 표기·링크보다 먼저 분모로 쓰고(1e9/2e9 = 50%) 근거에 「실측」을 적음", "실측 R 2,000/W 1,000" in txt and " 50.0%" in txt and "표기 R" not in txt, txt)
check("render: 그래프 줄(막대)이 수치 줄 아래에 따로 있음", any("█" in l and "%" not in l for l in txt.splitlines()), txt)
s2 = dict(s1, disk_info={"nvmeX": dict(model="X", name=None, read=None, write=None, link=None, bench=None)})
check("render: 기준이 없으면 벤치마크 안내(d)가 나오고 % 는 없음", "d: 짧은 디스크 벤치마크" in lv.render_io(s2, 70).plain)
finish("diskbench")
