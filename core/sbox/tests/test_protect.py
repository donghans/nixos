#!/usr/bin/env python3
"""sbox R7(가) 보호 경로 시험(plan sbox-project-policy R7·§3 ⑧, pilot §29-94). 네트워크·ct 없음 — 임시 폴더와 가짜 mountinfo 만.
시험 판정(donghans-test-judgment): 장기 보호용 — 제어 파일이 보호에서 빠지거나(패턴 확장 누락) 보호가 조용히 풀리는 길(심볼릭 링크·새 제어 파일·마운트 누락)을 막는 보안 불변식.
 ① 기본 집합 확장(CLAUDE.md·.claude·package.json·락·Dockerfile*·compose·.githooks·.github), 어디서든(깊이) 맞고 node_modules·.git 안은 제외 ② 폴더째 보호(안쪽 중복 제거)
 ③ 심볼릭 링크·공백/따옴표 경로·절대/.. 패턴은 거부 ④ mountinfo 판독(읽기 전용 마운트만 인정, 안쪽 rw 마운트·루트 ro 는 불인정)
 ⑤ [protect] add/remove 와 잘못된 형식 ⑥ taskd.check_protect: 옛 설정 통과·새 제어 파일은 stale·마운트 없음은 not-ro·위반은 invalid
실행: python3 -I core/sbox/tests/test_protect.py  (mods/_tools/run-tests.sh 의 sbox-protect)"""
import json, os, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import protect, tasks, taskd  # noqa: E402

n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


def raises(fn, frag=""):
    try:
        fn(); return False
    except (ValueError, SystemExit) as e:
        return frag in str(e)


def touch(root, rel, text="x"):
    p = os.path.join(root, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(text)


d = tempfile.mkdtemp(); root = os.path.join(d, "work"); os.makedirs(root)
for rel in ["CLAUDE.md", ".claude/settings.json", ".claude/hooks/a.sh", ".mcp.json", "package.json", "web/package.json", "package-lock.json",
            "Dockerfile", "docker/Dockerfile.dev", "svc/docker-compose.override.yml", ".github/workflows/ci.yml", ".githooks/pre-commit",
            "uv.lock", "src/app.js", "README.md", "node_modules/a/package.json", ".git/config", "node_modules/b/Dockerfile"]:
    touch(root, rel)
got = protect.expand(root, protect.DEFAULT_PROTECT)
want = ["CLAUDE.md", ".claude", ".mcp.json", "package.json", "web/package.json", "package-lock.json", "Dockerfile", "docker/Dockerfile.dev",
        "svc/docker-compose.override.yml", ".github", ".githooks", "uv.lock"]
check("기본 집합 확장(깊이·폴더째)", sorted(got) == sorted(want), sorted(set(got) ^ set(want)))
check("node_modules·.git 안은 제외", not any(x.startswith(("node_modules", ".git/")) for x in got), got)
check("폴더째 보호면 안쪽 파일은 따로 안 나옴", ".claude/settings.json" not in got and ".github/workflows/ci.yml" not in got)
check("없는 경로는 목록에 없음", ".githooks" in got and "go.sum" not in got and "Cargo.lock" not in got)

# ③ 거부
os.symlink("/etc/passwd", os.path.join(root, "yarn.lock"))
check("심볼릭 링크 제어 파일은 거부", raises(lambda: protect.expand(root, protect.DEFAULT_PROTECT), "심볼릭"))
os.unlink(os.path.join(root, "yarn.lock"))
touch(root, "Dockerfile weird")
check("공백 든 경로는 거부", raises(lambda: protect.expand(root, ["Dockerfile*"]), "공백"))
os.unlink(os.path.join(root, "Dockerfile weird"))
check("절대 패턴 거부", raises(lambda: protect.expand(root, ["/etc/passwd"]), "상대"))
check(".. 패턴 거부", raises(lambda: protect.expand(root, ["../x"]), "상대"))

# ④ mountinfo
mi = "\n".join([
    "20 1 0:5 / / rw - overlay overlay rw",
    "30 20 0:6 /w/package.json /home/sbox/work/package.json ro,relatime - btrfs x rw",
    "31 20 0:6 /w/.claude /home/sbox/work/.claude ro,relatime - btrfs x rw",
    "32 20 0:7 /w/.claude/tmp /home/sbox/work/.claude/tmp rw,relatime - tmpfs x rw",
    "33 20 0:6 /w/web /home/sbox/work/web rw,relatime - btrfs x rw",
])
W = "/home/sbox/work/"
check("ro 마운트 지점 인정", protect.mounted_ro(mi, W + "package.json"))
check("ro 폴더 안쪽 경로 인정", protect.mounted_ro(mi, W + ".claude/settings.json"))
check("rw 마운트는 불인정", not protect.mounted_ro(mi, W + "web"))
check("ro 폴더 안쪽 rw 마운트가 이김(보호 구멍)", not protect.mounted_ro(mi, W + ".claude/tmp/x"))
check("마운트 없는 경로 불인정", not protect.mounted_ro(mi, W + "Dockerfile"))
check("루트 ro 는 인정하지 않음", not protect.mounted_ro("1 0 0:1 / / ro - ext4 x ro", "/home/sbox/work/package.json"))

# ⑤ 매니페스트 [protect]
def mf(extra):
    p = os.path.join(d, "m.toml"); open(p, "w").write('[project]\nname = "p"\n' + extra); return p
check("기본 집합 그대로", tasks.protect_patterns(mf("")) == protect.DEFAULT_PROTECT)
pp = tasks.protect_patterns(mf('[protect]\nadd = ["scripts/gate.sh", "Makefile"]\nremove = ["package.json"]\n'))
check("add·remove 반영", "Makefile" in pp and "scripts/gate.sh" in pp and "package.json" not in pp and "CLAUDE.md" in pp, pp)
check("add 가 문자열 목록 아니면 거부", raises(lambda: tasks.protect_patterns(mf('[protect]\nadd = "x"\n')), "목록"))
check("add 절대 경로 거부", raises(lambda: tasks.protect_patterns(mf('[protect]\nadd = ["/etc/x"]\n')), "상대"))
cfg, _ = tasks.build(mf(""), {}, False, ["package.json"])
check("build 가 protect·protected 를 설정에 담음", cfg["protect"] == protect.DEFAULT_PROTECT and cfg["protected"] == ["package.json"], cfg.get("protect"))

# ⑥ taskd.check_protect
r2 = os.path.join(d, "w2"); os.makedirs(r2); touch(r2, "package.json"); touch(r2, "src/a.js")
td = taskd.Taskd(os.path.join(d, "none.json"), os.path.join(d, "t.log"))
ro = "1 0 0:1 /p %s ro - btrfs x rw" % os.path.join(r2, "package.json")
c0 = {"root": r2}
check("보호 설정이 없는 옛 설정은 통과", td.check_protect(c0) == "")
c1 = {"root": r2, "protect": protect.DEFAULT_PROTECT, "protected": ["package.json"]}
check("목록 일치+ro 마운트면 통과", td.check_protect(c1, ro) == "")
touch(r2, "Dockerfile")
check("새 제어 파일이 생기면 stale", td.check_protect(c1, ro).startswith("protect-stale:Dockerfile"), td.check_protect(c1, ro))
os.unlink(os.path.join(r2, "Dockerfile"))
check("ro 마운트가 없으면 not-ro", td.check_protect(c1, "1 0 0:1 / / rw - x x rw").startswith("protect-not-ro:package.json"))
os.symlink("/etc/passwd", os.path.join(r2, "go.sum"))
check("링크 제어 파일은 invalid", td.check_protect(c1, ro).startswith("protect-invalid"))

# ⑦ 소켓 경유: run 이 check_protect 를 실제로 부른다(stale 이면 거부, 해소되면 실행)
import shutil, socket, threading, time
r3 = os.path.join(d, "w3"); os.makedirs(r3); touch(r3, "package.json")
cp3 = os.path.join(d, "c3.json")
json.dump({"version": 1, "root": r3, "home": d, "logdir": d, "protect": ["Dockerfile*"], "protected": [],
           "tasks": {"t": {"argv": [shutil.which("echo") or "/bin/echo", "ran"], "cwd": ".", "kind": "oneshot"}}}, open(cp3, "w"))
td3 = taskd.Taskd(cp3, os.path.join(d, "t3.log")); s3 = os.path.join(d, "s3.sock")
threading.Thread(target=taskd.serve, args=(td3, s3, {os.getuid()}), daemon=True).start()
for _ in range(50):
    if os.path.exists(s3):
        break
    time.sleep(0.05)


def ask3():
    c = socket.socket(socket.AF_UNIX); c.settimeout(10); c.connect(s3); c.sendall(b'{"op":"run","task":"t"}\n')
    buf = b""
    while True:
        x = c.recv(65536)
        if not x:
            break
        buf += x
    c.close(); return buf.decode()


touch(r3, "Dockerfile")
check("소켓 run: 새 제어 파일이 있으면 protect-stale 로 거부", "protect-stale:Dockerfile" in ask3())
os.unlink(os.path.join(r3, "Dockerfile"))
check("소켓 run: 해소되면 실행", "ran" in ask3())
print(f"sbox-protect {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
