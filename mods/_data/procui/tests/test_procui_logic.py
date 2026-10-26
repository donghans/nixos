#!/usr/bin/env python3
"""procui 순수 로직 시험: 스냅샷·그룹 배정(누락·중복 0)·규칙/필터/TOML·보호(뷰와 독립)·계획·pidfd 종료(PID 재사용 방어).
실제 시스템 프로세스에는 신호를 보내지 않는다 — 시험이 직접 띄운 고유 이름의 sleep 자식 프로세스만 대상."""
import os, shutil, signal, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); DATA = os.path.dirname(ROOT)
for p in (ROOT, os.path.join(DATA, "observe"), os.path.join(DATA, "_testkit"), os.path.join(DATA, "claude-skills", "donghans-host-resources", "scripts")):
    sys.path.insert(0, p)
import procscan as ps, procgroups as pg, procactions as pa
import observe_apps
from harness import checker
check, finish = checker()
TMP = tempfile.mkdtemp(prefix="procui-test-")

# --- 스냅샷
procs = ps.annotate(ps.scan(), observe_apps.AppResolver())
bp = ps.by_pid(procs)
me = os.getpid()
check("scan: 자기 자신이 있고 필드가 채워짐(start>0, uid=내 UID, cgroup 경로)", me in bp and bp[me]["start"] > 0 and bp[me]["uid"] == os.getuid() and bp[me]["cgroup"].startswith("/"))
check("scan: PID 1 과 커널 스레드(kthreadd) 표시", 1 in bp and any(p["kernel"] for p in procs) and not bp[1]["kernel"])
check("parse_stat: comm 에 공백·괄호가 있어도 파싱", ps.parse_stat("12 (a (b) c) S 1 2 3")[0] == "a (b) c" and ps.parse_stat("12 (x) S 1 2")[1][:2] == ["S", "1"])
check("ancestors: 자신과 PID 1 까지 포함", {me, 1} <= ps.ancestors(me, bp))
check("with_cpu: 첫 스냅샷은 0, 같은 틱이면 0, 늘면 코어 1개=100% 기준", ps.with_cpu([dict(pid=1, start=1, ticks=100, cpu=0.0)], {}, 1.0) and ps.with_cpu([p := dict(pid=1, start=1, ticks=100 + ps.HZ, cpu=0.0)], {(1, 1): 100}, 1.0) and abs(p["cpu"] - 100) < 1e-6)
check("unit_of: 마지막 구성요소와 \\x2d 복원", ps.unit_of("/user.slice/app-a\\x2db.scope") == "app-a-b.scope" and ps.unit_of("") == "/")

# --- 뷰: 모든 프로세스가 정확히 한 그룹
ctx = pg.Ctx(procs)
for v in pg.BUILTIN_VIEWS:
    gs = pg.build_groups(procs, v, ctx)
    pids = [p["pid"] for g in gs for p in g["procs"]]
    check(f"뷰 '{v['name']}': 모든 프로세스가 정확히 한 그룹(누락·중복 0)", sorted(pids) == sorted(p["pid"] for p in procs) and len(set(pids)) == len(pids), f"{len(pids)} vs {len(procs)}")
own = pg.build_groups(procs, pg.BUILTIN_VIEWS[0], ctx)
check("소유 뷰: 그룹 이름이 기대 집합 안(커널·컨테이너·VM·시스템·내 환경·내 작업·(기타))", {g["name"] for g in own} <= {"커널", "컨테이너·VM", "시스템", "내 환경", "내 작업", "(기타)"})
check("소유 뷰: 이 시험 프로세스(내 UID, 데스크톱 아님)는 내 작업", pg.classify(pg.BUILTIN_VIEWS[0], bp[me], ctx) == "내 작업")
fake = lambda **kw: dict(dict(pid=9000, ppid=1, comm="x", exe="x", uid=1000, start=5, ticks=0, rss=10 << 20, threads=1, state="S", cgroup="/user.slice/user-1000.slice/user@1000.service/app.slice/app-x.scope", kernel=False, cpu=0.0, app="x"), **kw)
fp = [fake(pid=1, ppid=0, comm="systemd", exe="systemd", app="systemd", uid=0, cgroup="/init.scope"),
      fake(pid=10, ppid=1, comm="hyprland", app="hyprland"), fake(pid=11, ppid=1, comm="firefox", app="firefox"),
      fake(pid=12, ppid=1, comm=".claude-wrapped", app="claude"), fake(pid=13, ppid=12, comm="python3", app="python3", cpu=70.0),
      fake(pid=14, ppid=1, comm="qemu-system-x86", app="qemu-system-x86", uid=0, cgroup="/system.slice/incus.service"),
      fake(pid=2, ppid=0, comm="kthreadd", exe="", app="kthreadd", uid=0, kernel=True, cgroup="")]
fc = pg.Ctx(fp, me=1000)
own_v = pg.BUILTIN_VIEWS[0]
check("소유 규칙: 커널·VM·시스템(root)·내 환경·내 작업 분류", [pg.classify(own_v, p, fc) for p in fp] == ["시스템", "내 환경", "내 작업", "내 작업", "내 작업", "컨테이너·VM", "커널"])
check("세션 뷰: LLM 세션과 그 자식은 같은 라벨, 밖은 (세션 밖)", pg.classify(pg.BUILTIN_VIEWS[3], fp[3], fc) == pg.classify(pg.BUILTIN_VIEWS[3], fp[4], fc) == "claude #12" and pg.classify(pg.BUILTIN_VIEWS[3], fp[2], fc) == pg.NO_SESSION)
check("세션 뷰: 세션 이름 맵이 있으면 그 이름", pg.classify(pg.BUILTIN_VIEWS[3], fp[4], pg.Ctx(fp, me=1000, session_names={12: "nixos-c9"})) == "nixos-c9")
check("규칙: ancestor_app·cpu_gt·rss_gt·session 조건", pg.rule_matches(dict(group="g", ancestor_app=["claude"], cpu_gt=50), fp[4], fc) and not pg.rule_matches(dict(group="g", ancestor_app=["claude"], cpu_gt=80), fp[4], fc) and pg.rule_matches(dict(group="g", rss_gt="5M", session=True), fp[4], fc) and not pg.rule_matches(dict(group="g", rss_gt="50M"), fp[4], fc))

# --- 사용자 설정(TOML)
cfg = os.path.join(TMP, "groups.toml")
open(cfg, "w").write('''
[[view]]
name = "작업별"
[[view.rule]]
group = "브라우저"
app = ["firefox", "vivaldi"]
[[view.rule]]
group = "고장난 규칙"
nosuchkey = 1
[[view.rule]]
app = ["x"]
[[view]]
name = "앱"
default = "@comm"
[[view.rule]]
group = "내 세션"
session = true
[protect]
app = ["firefox"]
comm = "mytool*"
''')
ev, prot, w = pg.load_config(cfg)
check("load_config: 정상 뷰·규칙 로드, 모르는 조건·group 없는 규칙은 경고와 함께 버림", [v["name"] for v in ev] == ["작업별", "앱"] and len(ev[0]["rules"]) == 1 and len(w) == 2, w)
check("load_config: [protect] 문자열은 리스트로", prot == {"app": ["firefox"], "comm": ["mytool*"]})
mv = pg.merge_views(pg.BUILTIN_VIEWS, ev)
check("merge_views: 같은 이름 내장 뷰는 사용자 규칙이 앞·default 교체, 새 이름은 뒤에", [v["name"] for v in mv][-1] == "작업별" and mv[1]["rules"][0]["group"] == "내 세션" and mv[1]["default"] == "@comm" and len(mv[1]["rules"]) == 1)
check("merge_views: 내장 뷰 원본은 변경되지 않음", pg.BUILTIN_VIEWS[1]["rules"] == [] and pg.BUILTIN_VIEWS[1]["default"] == "@app")
check("사용자 뷰 적용: firefox 는 브라우저, 나머지는 기타", [pg.classify(mv[-1], p, fc) for p in fp[1:4]] == ["(기타)", "브라우저", "(기타)"])
bad = os.path.join(TMP, "bad.toml"); open(bad, "w").write("[[view\nname = ")
check("load_config: 문법이 깨진 파일·없는 파일은 예외 없이 경고/빈 값", pg.load_config(bad)[2] and pg.load_config(os.path.join(TMP, "none.toml")) == ([], {"app": [], "comm": []}, []))

# --- 필터
pred, fw = pg.parse_filter("python cpu>50 mem>5M")
check("필터: 이름·cpu·mem AND", pred(fp[4], "g") and not pred(fp[3], "g"))
check("필터: user:root·group:·app:·pid:", pg.parse_filter("user:root")[0](fp[0], "g") and not pg.parse_filter("user:root")[0](fp[1], "g") and pg.parse_filter("group:빌")[0](fp[1], "빌드") and pg.parse_filter("app:fire")[0](fp[2], "g") and pg.parse_filter("pid:13")[0](fp[4], "g"))
check("필터: 읽을 수 없는 토큰은 경고하고 무시", pg.parse_filter("cpu>abc")[1] and pg.parse_filter("")[0](fp[0], "g"))
check("parse_size: 500M·2g·1KiB·123", pg.parse_size("500M") == 500 << 20 and pg.parse_size("2g") == 2 << 30 and pg.parse_size("1KiB") == 1024 and pg.parse_size("123") == 123)

# --- 보호(뷰와 독립)
pc = pa.PCtx(fp, self_pid=13, me=1000)
code = lambda p, c=pc: {x for x, _ in pa.protect_reasons(p, c)}
check("보호: PID 1·조상(12 = 13 의 부모)·자기 자신·커널·다른 UID 는 하드", {"pid1", "other-uid"} <= code(fp[0]) and "self" in code(fp[3]) and "self" in code(fp[4]) and "kernel" in code(fp[6]) and "other-uid" in code(fp[5]))
check("보호: 소프트(데스크톱·VM·LLM 세션) 이름 판정, 일반 앱은 없음", "desktop" in code(fp[1]) and "vm-container" in code(fp[5]) and "llm-session" in code(fp[3]) and code(fp[2]) == set())
check("보호: nix·세션 인프라·관측 수집기", "nix" in code(fake(comm="nixos-rebuild", app="nixos-rebuild", exe="nixos-rebuild")) and "infra" in code(fake(comm="sshd", app="sshd")) and "infra" in code(fake(comm="observe-collector", app="observe-collector")))
pcu = pa.PCtx(fp, extra=prot, self_pid=13, me=1000)
check("보호: 사용자 [protect] 규칙(app/comm 글롭)", "user" in code(fp[2], pcu) and "user" in code(fake(comm="mytool-x", app="mytool-x"), pcu) and "user" not in code(fp[2], pc))
check("보호: 뷰 규칙을 바꿔도(hyprland 를 '내 작업'으로 분류) 보호는 그대로", pg.classify(dict(name="t", default="내 작업", rules=[]), fp[1], fc) == "내 작업" and "desktop" in code(fp[1]))
pc2 = pa.PCtx(fp, self_pid=11, me=1000)
check("보호: 조상은 self_pid 에 따라 다시 계산됨(11 이면 12 는 조상 아님)", "self" not in code(fp[3], pc2) and "self" in code(fp[2], pc2))

# --- 계획
sel = {pa.key(fp[2]), pa.key(fp[1]), pa.key(fp[0]), pa.key(fp[3])}
plan = pa.build_plan(fp, sel, set(), pc)
check("계획: 일반 앱만 대상, 보호된 것은 사유와 함께 제외", [p["pid"] for p in plan["targets"]] == [11] and {p["pid"] for p, _ in plan["excluded"]} == {1, 10, 12})
plan = pa.build_plan(fp, sel, {pa.key(fp[1]), pa.key(fp[0]), pa.key(fp[3])}, pc)
check("계획: 소프트 보호는 override 로 대상이 되고, 하드(PID 1·조상)는 override 여도 제외", {p["pid"] for p in plan["targets"]} == {11, 10} and {p["pid"] for p, _ in plan["excluded"]} == {1, 12})
check("계획: 선택에 없는 프로세스는 무시, 자식(선택 밖)은 별도로 셈", pa.build_plan(fp, {pa.key(fp[3])}, {pa.key(fp[3])}, pa.PCtx(fp, self_pid=11, me=1000))["children_separate"] == 1 and pa.build_plan(fp, set(), set(), pc)["targets"] == [])

# --- 실제 종료(시험이 띄운 프로세스만)
check("pidfd 지원(이 파이썬·커널)", pa.supported())
def spawn(n):
    name = f"ptest{os.getpid()}x{n}"[:15]       # comm 은 prctl(PR_SET_NAME) 로 고유하게 — 다른 사용자의 sleep 과 섞이지 않게
    pr = subprocess.Popen([sys.executable, "-c", f"import ctypes,time; ctypes.CDLL(None).prctl(15, b'{name}'); time.sleep(300)"])
    time.sleep(0.4)
    return pr, name
def snap():
    s = ps.annotate(ps.scan(), observe_apps.AppResolver())
    return s, {p["pid"]: p for p in s}
a, _ = spawn(1); b, _ = spawn(2)
s, bp2 = snap()
ta, tb = bp2[a.pid], bp2[b.pid]
check("시험 프로세스가 스냅샷에 고유 이름으로 보임", ta["comm"].startswith("ptest") and not pa.protect_reasons(ta, pa.PCtx(s)))
bad_item = dict(tb, start=tb["start"] + 1)     # PID 재사용 시뮬레이션: 계획 때 저장한 시작 시각이 다름
res, alive = pa.send([bad_item], signal.SIGTERM, wait=0.3)
check("PID 재사용 방어: 시작 시각이 다르면 신호를 보내지 않음(프로세스 생존)", res[0]["status"] == "mismatch" and b.poll() is None and not alive)
res, alive = pa.send([ta], signal.SIGTERM, wait=3.0)
check("SIGTERM: 보내고 종료까지 기다림(대기 중 살아남은 것 없음, 프로세스 종료됨)", res[0]["status"] == "sent" and not alive and a.wait(timeout=2) == -signal.SIGTERM)
res, alive = pa.send([ta], signal.SIGTERM, wait=0.3)
check("이미 종료된 대상은 gone", res[0]["status"] in ("gone", "mismatch"))
ign = subprocess.Popen(["sh", "-c", "trap '' TERM; while :; do sleep 1; done"]); time.sleep(0.3)
s, bp3 = snap()
res, alive = pa.send([bp3[ign.pid]], signal.SIGTERM, wait=0.5, override={pa.key(bp3[ign.pid])})
check("SIGTERM 을 무시하는 프로세스는 살아남은 목록에 남음", res[0]["status"] == "sent" and [p["pid"] for p in alive] == [ign.pid] and ign.poll() is None)
res, alive = pa.send(alive, signal.SIGKILL, wait=2.0, override={pa.key(bp3[ign.pid])})
check("남은 것에 SIGKILL 을 다시 보내면 종료", res[0]["status"] == "sent" and not alive and ign.wait(timeout=2) == -signal.SIGKILL)
sh = ps.scan()
selfp = next(p for p in sh if p["pid"] == os.getpid())
res, _ = pa.send([selfp], signal.SIGTERM, wait=0.1)
check("자기 자신(시험 프로세스)에게는 신호 직전 재계산에서 거부됨(죽지 않았으니 이 줄이 찍힘)", res[0]["status"] == "protected" and "자신" in res[0]["detail"])
res, _ = pa.send([next(p for p in sh if p["pid"] == 1)], signal.SIGTERM, wait=0.1, override={pa.key(next(p for p in sh if p["pid"] == 1))})
check("PID 1 은 override 를 줘도 거부(하드 보호)", res[0]["status"] in ("protected", "denied", "error"), res)
b.kill(); b.wait()

# --- 기록
lp = os.path.join(TMP, "state", "procui", "actions.jsonl")
check("log: jsonl 로 시각·그룹·이름·PID·신호·결과만 기록, 명령 인자 키 없음", pa.log(lp, [dict(pid=1, comm="x", sig=15, status="sent", detail="")], group="g") and set(__import__("json").loads(open(lp).read().splitlines()[0])) == {"t", "group", "pid", "comm", "sig", "status", "detail"})
check("log: 쓸 수 없는 경로는 예외 없이 False", pa.log("/proc/nope/x.jsonl", []) is False)
detail = ps.detail(selfp, sh, {"소유": "내 작업"})
check("detail: 세부 항목(CPU·메모리·FD·IO·cgroup·부모 사슬·자식·그룹)이 모두 나옴", all(any(h in line for line in detail) for h in ("CPU", "메모리", "열린 FD", "I/O", "cgroup", "부모 사슬", "자식", "그룹")))
finish("procui_logic")
