#!/usr/bin/env python3
"""sbox depwatch 시험(plan sbox-depwatch §4). 임시 HOME·임시 저장소 픽스처만 쓰고 네트워크·실제 ~/.config/sbox 는 건드리지 않는다.
지키는 것:
 ① 락 파일 없음·설치 스크립트 보유 패키지는 반드시 발견 사항으로 잡힌다(못 잡으면 사용자는 안전하다고 믿는다)
 ② `tools.py plan`(= `sboxctl tools --update`)이 매니페스트를 다시 써도 사람이 정한 tier 가 유지된다(안 그러면 critical 이 조용히 general 로 돌아간다)
 ③ `depwatch list --json` 은 ctl 공통 봉투(command·ok·structured·exit_code·data)를 낸다(llmui·LLM 이 읽는 계약)
 ④ depwatch.py 는 표준 라이브러리만 쓴다 — 스토어 사본(waybar 타이머의 `tools.py periodic`)처럼 저장소 바깥 경로 없이 혼자 있어도 scan 이 돈다
실행: python3 -I core/sbox/tests/test_depwatch.py  (mods/_tools/run-tests.sh 의 sbox-depwatch)"""
import json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # core/sbox
TMP = tempfile.mkdtemp()
os.environ["HOME"] = TMP                          # manifest_path·STATE 가 임시 HOME 을 쓰게 — import 전에 설정
os.environ["SBOX_DEPWATCH_STATE"] = os.path.join(TMP, "state", "depwatch.json")
os.environ["SBOX_MANIFESTS"] = os.path.join(TMP, ".config", "sbox", "manifests")
sys.path.insert(0, ROOT)
import depwatch, tools  # noqa: E402

n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


def mk(path, files):
    os.makedirs(path, exist_ok=True)
    for f, content in files.items():
        os.makedirs(os.path.dirname(os.path.join(path, f)), exist_ok=True)
        with open(os.path.join(path, f), "w", encoding="utf-8") as fh:
            fh.write(content if isinstance(content, str) else json.dumps(content))


repos = os.path.join(TMP, "repos")
mk(os.path.join(repos, "nolock"), {"package.json": {"name": "a"}})
mk(os.path.join(repos, "scripts"), {"package.json": {"name": "b"}, "package-lock.json": {
    "lockfileVersion": 3, "packages": {"": {"name": "b"}, "node_modules/esbuild": {"version": "1.0.0", "hasInstallScript": True},
                                       "node_modules/left-pad": {"version": "1.0.0"}}}})
mk(os.path.join(repos, "clean"), {"package.json": {"name": "c"}, "package-lock.json": {"lockfileVersion": 3, "packages": {"": {"name": "c"}, "node_modules/x": {"version": "1"}}}})
mk(os.path.join(repos, "nested"), {"web/package.json": {"name": "w"}, "node_modules/dep/package.json": {"name": "dep"}})

# ① 감지기
kinds = lambda r: sorted(f["kind"] for f in depwatch.npm_findings(os.path.join(repos, r)))  # noqa: E731
check("락 없는 npm 프로젝트는 no-lock", kinds("nolock") == ["no-lock"], kinds("nolock"))
sc = depwatch.npm_findings(os.path.join(repos, "scripts"))
check("hasInstallScript 패키지는 install-script, 이름이 근거에 나옴", [f["kind"] for f in sc] == ["install-script"] and "esbuild" in sc[0]["evidence"] and "left-pad" not in sc[0]["evidence"], sc)
check("정상 프로젝트는 발견 없음", kinds("clean") == [], kinds("clean"))
check("한 단계 아래 package.json 도 보고 node_modules 는 제외", kinds("nested") == ["no-lock"], kinds("nested"))

# 실제 저장소(genple)에서 드러난 두 경우: 깊은 위치의 package.json 도 보고, 워크스페이스 멤버는 상위 락을 쓴다(오탐 방지)
lockfile = {"lockfileVersion": 3, "packages": {"": {"name": "r"}}}
mk(os.path.join(repos, "ws"), {
    "package.json": {"name": "r", "workspaces": ["client", "packages/*"]}, "package-lock.json": lockfile,
    "client/package.json": {"name": "client"}, "packages/a/package.json": {"name": "a"},
    "other/package.json": {"name": "other"},               # 워크스페이스에 안 들어간 하위 프로젝트 — 락 없음으로 잡혀야 함
    "deep/x/y/package.json": {"name": "y"}})               # 깊이 3 — 놓치면 안 됨
ws = sorted(f["id"] for f in depwatch.npm_findings(os.path.join(repos, "ws")))
mk(os.path.join(repos, "vend"), {"package.json": {"name": "v"}, "package-lock.json": lockfile, "vendor/lib/package.json": {"name": "lib"}, "app/package.json": {"name": "app"}})
vf = {f["id"]: f["severity"] for f in depwatch.npm_findings(os.path.join(repos, "vend"))}
check("vendor 하위의 락 없음은 info 로 낮추고 일반 하위는 warn 유지", vf == {"npm.no-lock:vendor/lib": "info", "npm.no-lock:app": "warn"}, vf)
check("워크스페이스 멤버(client·packages/*)는 상위 락 사용 — 오탐 없음, 멤버가 아닌 other·깊은 deep/x/y 는 no-lock",
      ws == ["npm.no-lock:deep/x/y", "npm.no-lock:other"], ws)

# ② tier 보존 — plan() 은 inferred 가 비는 저장소(.nvmrc 등 없음)로 돌려 네트워크 해석을 피한다
os.makedirs(depwatch.MANIFESTS, exist_ok=True)
tools.plan(["--repo", os.path.join(repos, "scripts")])
mpath = os.path.join(depwatch.MANIFESTS, "scripts.toml")
with open(mpath, "a", encoding="utf-8") as f:
    f.write("\n# 사람이 단 주석\n")
depwatch.set_tier("scripts", "critical")
txt = open(mpath, encoding="utf-8").read()
check("set_tier 는 [project] 안에 tier 한 줄만 넣고 주석·다른 구역은 보존", 'tier = "critical"' in txt and "# 사람이 단 주석" in txt and "[inferred]" in txt and txt.index('tier = "critical"') < txt.index("\n[inferred]"), txt)
tools.plan(["--repo", os.path.join(repos, "scripts"), "--update"])
import tomllib  # noqa: E402
after = tomllib.load(open(mpath, "rb"))
check("plan --update 로 매니페스트를 다시 써도 tier 유지", after["project"].get("tier") == "critical", after)
try:
    depwatch.set_tier("scripts", "bogus")
    check("잘못된 tier 값은 거부", False)
except ValueError:
    check("잘못된 tier 값은 거부", True)

# scan: 등급·first_seen 유지
mk(os.path.join(TMP, ".config", "sbox", "manifests"), {})
tools.plan(["--repo", os.path.join(repos, "nolock")])
r1 = depwatch.scan()
st1 = depwatch.listing()
check("scan 은 두 프로젝트를 기록하고 critical 등급을 담는다", set(r1) == {"scripts", "nolock"} and st1["projects"]["scripts"]["tier"] == "critical" and st1["projects"]["nolock"]["tier"] == "general", st1)
first = st1["projects"]["nolock"]["findings"][0]["first_seen"]
check("발견이 있으면 건수가 맞다", r1["nolock"] == 1 and r1["scripts"] == 1, r1)
depwatch.scan()
check("다시 스캔해도 first_seen 유지", depwatch.listing()["projects"]["nolock"]["findings"][0]["first_seen"] == first)

# ③ 봉투
env = dict(os.environ)
p = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "depwatch.py"), "list", "--json"], capture_output=True, text=True, env=env)
try:
    env_json = json.loads(p.stdout)
except ValueError:
    env_json = {}
check("list --json 은 ctl 봉투 키를 낸다", p.returncode == 0 and all(k in env_json for k in ("command", "ok", "structured", "exit_code", "data")) and env_json.get("ok") is True and env_json.get("structured") is True and "projects" in env_json.get("data", {}), p.stdout + p.stderr)
p = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "depwatch.py"), "list", "--project", "없는프로젝트", "--json"], capture_output=True, text=True, env=env)
try:
    err_json = json.loads(p.stdout)
except ValueError:
    err_json = {}
check("없는 프로젝트는 ok=false 봉투 + 종료 코드 1", p.returncode == 1 and err_json.get("ok") is False and err_json.get("exit_code") == 1, p.stdout + p.stderr)

# ④ 혼자 있어도 scan 이 돈다(저장소 바깥 import 없음)
alone = tempfile.mkdtemp()
shutil.copy(os.path.join(ROOT, "depwatch.py"), alone)
p = subprocess.run([sys.executable, "-I", os.path.join(alone, "depwatch.py"), "scan"], capture_output=True, text=True, env=env, cwd=alone)
check("depwatch.py 단독(스토어 사본 같은 환경) scan", p.returncode == 0 and "nolock" in p.stdout, p.stdout + p.stderr)

shutil.rmtree(TMP, ignore_errors=True)
shutil.rmtree(alone, ignore_errors=True)
print(f"sbox-depwatch {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
