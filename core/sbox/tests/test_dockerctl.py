#!/usr/bin/env python3
"""sbox ct 안 Docker 설치 계획(`dockerctl.py`) 시험(plan dev-sandbox-pilot §29-15, S53·S55). 네트워크 없음 — `tools._head_date` 를 가짜로 바꾸고 날짜는 오늘 기준 상대값.
지키는 것:
 ① 키 규칙: `pub` 레코드가 정확히 하나이고 그 지문이 공식 값일 때만 통과 — 공식 키에 공격자 키를 하나 더 붙인 파일은 거부(「공식 지문이 파일 어딘가에 있다」로는 통과하면 안 됨)
 ② 버전 선택: apt 의 .deb 공개일이 쿨다운(7일)보다 젊은 docker-ce·containerd.io 는 건너뛰고, docker-ce 는 cli·rootless-extras 에 같은 버전이 있는 것만 고른다
 ③ 매니페스트: [resolved.docker] 갱신이 사람이 쓴 [override]·등급·다른 도구 구역을 건드리지 않고, 도구 층 plan 이 다시 써도 [resolved.docker] 를 잃지 않는다(재현성)
 ④ 필요 판정: compose·Dockerfile 은 의존성 폴더 밖에서만, 매니페스트의 고정 기록도 근거
실행: python3 -I core/sbox/tests/test_dockerctl.py  (mods/_tools/run-tests.sh 의 sbox-dockerctl). gpg 가 없고 nix 도 없으면 ① 은 건너뛴다(알림)."""
import os, shutil, subprocess, sys, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp()
os.environ["SBOX_DOCKER_KEYDIR"] = os.path.join(TMP, "keys")
os.environ.pop("SBOX_TOOLS_MIN_AGE_DAYS", None)
sys.path.insert(0, ROOT)
import tools, dockerctl  # noqa: E402,E401

n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


now = time.time()
ago = lambda d: now - d * 86400  # noqa: E731

# ② 버전 선택
SFX = "~debian.13~trixie"
def ent(pkg, ver, fn=None):
    return {"Package": pkg, "Version": ver, "Filename": fn or f"pool/{pkg}_{ver}.deb"}
E = []
for v in ("5:29.9.3-1", "5:29.10.0-1", "5:29.8.0-1"):                       # 29.10.0 이 숫자로 가장 새것(문자열 정렬이면 29.9.3 이 앞서 틀림)
    E += [ent(p, v + SFX) for p in dockerctl.PKGS]
E += [ent("docker-ce", "5:29.11.0-1" + SFX)]                                 # 가장 새것이지만 cli·rootless-extras 가 아직 없음 → 고르면 안 됨
E += [ent("containerd.io", "2.4.2-4" + SFX), ent("containerd.io", "2.5.0-1" + SFX)]
age = {"29.11.0": 30, "29.10.0": 3, "29.9.3": 20, "29.8.0": 60, "2.5.0": 2, "2.4.2": 25}   # 일 단위 나이
def fake_head(url):
    for k, d in age.items():
        if f"_{k}" in url or f"_5:{k}" in url:
            return ago(d)
    return None
tools._head_date = fake_head
dv, cv, notes = dockerctl.choose(E, "https://x", now)
check("docker-ce: cli·extras 가 없는 29.11.0 은 건너뛰고, 3일 된 29.10.0 도 건너뛰어 20일 된 29.9.3 을 고른다(숫자 정렬)", dv == "5:29.9.3-1" + SFX, dv)
check("containerd.io: 2일 된 2.5.0 은 건너뛰고 25일 된 2.4.2 를 고른다(docker-ce 와 따로)", cv == "2.4.2-4" + SFX, cv)
check("쿨다운으로 건너뛴 사실을 알린다", any("건너뛰" in x for x in notes), notes)
os.environ["SBOX_TOOLS_MIN_AGE_DAYS"] = "0"
dv0, _, _ = dockerctl.choose(E, "https://x", now)
check("SBOX_TOOLS_MIN_AGE_DAYS=0 이면 쿨다운을 끄고 cli 가 있는 가장 새 29.10.0", dv0 == "5:29.10.0-1" + SFX, dv0)
os.environ["SBOX_TOOLS_MIN_AGE_DAYS"] = "90"
try:
    dockerctl.choose(E, "https://x", now); check("전부 90일 미만이면 거부", False)
except SystemExit:
    check("전부 90일 미만이면 거부", True)
os.environ.pop("SBOX_TOOLS_MIN_AGE_DAYS")
pk = dockerctl.parse_packages("Package: docker-ce\nVersion: 5:1.0-1~debian.13~x\nFilename: a/b.deb\nDescription: x\n y\n\nPackage: foo\nVersion: 1\n")
check("parse_packages: 필수 필드 없는 항목은 빼고 읽는다", len(pk) == 1 and pk[0]["Filename"] == "a/b.deb", pk)

# ③ 매니페스트
mf = os.path.join(TMP, "m.toml")
open(mf, "w", encoding="utf-8").write('# 사람 주석\n[project]\nname = "p"\nrepo = "/r"\ntier = "critical"\n\n[inferred]\nnode = "22"  # 출처: .nvmrc\n\n[override]\ngo = "1.22"\n\n[resolved.node]\nspec = "22"\nversion = "22.1.0"\n')
dockerctl.write_resolved(mf, "5:29.9.3-1" + SFX, "2.4.2-4" + SFX)
dockerctl.write_resolved(mf, "5:29.8.0-1" + SFX, "2.4.2-4" + SFX)   # 두 번 써도 구역은 하나
txt = open(mf, encoding="utf-8").read()
check("[resolved.docker] 구역은 하나뿐이고 마지막 값", txt.count("[resolved.docker]") == 1 and "29.8.0" in txt and "29.9.3" not in txt, txt)
check("사람이 쓴 주석·tier·[override]·다른 도구 구역·출처 주석이 그대로", all(x in txt for x in ("# 사람 주석", 'tier = "critical"', 'go = "1.22"', "[resolved.node]", "# 출처: .nvmrc")), txt)
check("read_resolved 가 같은 값을 읽는다", dockerctl.read_resolved(mf).get("version") == "5:29.8.0-1" + SFX)
# 도구 층이 매니페스트를 다시 쓴다(네트워크를 타지 않게 해석할 도구가 없는 매니페스트로)
open(mf + "2", "w", encoding="utf-8").write('[project]\nname = "q"\nrepo = ""\n\n[resolved.docker]\nspec = "engine"\nversion = "5:29.9.3-1' + SFX + '"\ncontainerd = "2.4.2-4' + SFX + '"\n')
tools.plan(["--manifest", mf + "2"])
t2 = open(mf + "2", encoding="utf-8").read()
check("도구 층 plan 이 매니페스트를 다시 써도 [resolved.docker](containerd 포함)를 잃지 않는다", "[resolved.docker]" in t2 and "containerd" in t2 and "5:29.9.3-1" in t2, t2)

# ④ 필요 판정
R = os.path.join(TMP, "repo")
os.makedirs(os.path.join(R, "node_modules", "x")); os.makedirs(os.path.join(R, "a", "b", "c"))
open(os.path.join(R, "node_modules", "x", "Dockerfile"), "w").close()
check("의존성 폴더 안의 Dockerfile 은 근거가 아니다", dockerctl.wanted(R) is None)
open(os.path.join(R, "a", "b", "c", "compose.yaml"), "w").close()
check("깊이 3 아래의 compose 는 보지 않는다(비용·오탐 제한)", dockerctl.wanted(R) is None)
open(os.path.join(R, "a", "docker-compose.prod.yml"), "w").close()
check("깊이 2 이내의 docker-compose.*.yml 은 근거", (dockerctl.wanted(R) or "").startswith("yes"), dockerctl.wanted(R))
check("매니페스트에 [resolved.docker] 가 있으면 저장소 없이도 필요", (dockerctl.wanted(None, mf) or "").startswith("yes"))
mo = os.path.join(TMP, "ov.toml")
open(mo, "w", encoding="utf-8").write('[project]\nname = "o"\nrepo = ""\n\n[override]\ndocker = "no"\n\n[resolved.docker]\nspec = "engine"\nversion = "5:1-1"\ncontainerd = "1-1"\n')
check("[override] docker = \"no\" 는 [resolved.docker] 기록·저장소 감지보다 우선(영구히 끔)", dockerctl.wanted(R, mo) is None)
open(mo, "w", encoding="utf-8").write('[project]\nname = "o"\nrepo = ""\n\n[override]\ndocker = "yes"\n')
check("[override] docker = \"yes\" 는 저장소에 근거가 없어도 필요", (dockerctl.wanted(os.path.join(TMP, "nope"), mo) or "").startswith("yes"))
tools.plan(["--manifest", mo])
check("도구 층 plan 이 [override] docker 를 도구로 오인하지 않고(경고 없음) 다시 써도 보존", 'docker = "yes"' in open(mo, encoding="utf-8").read())
check("둘 다 없으면 no(None)", dockerctl.wanted(os.path.join(TMP, "nope"), os.path.join(TMP, "nope.toml")) is None)

# ① 키 규칙 — 임시 gpg 홈에 키를 만든다
if shutil.which("gpg") or shutil.which("nix"):
    gh = os.path.join(TMP, "gh"); os.makedirs(gh, mode=0o700)
    g = lambda *a, **k: subprocess.run(tools.gpg_cmd() + ["--homedir", gh, "--batch", "--pinentry-mode", "loopback", "--passphrase", ""] + list(a), capture_output=True, text=True, **k)  # noqa: E731
    for u in ("official", "attacker"):
        g("--quick-gen-key", f"{u} <{u}@example.org>", "ed25519", "cert", "never")
    def fpr(u):
        return [ln.split(":")[9] for ln in g("--list-keys", "--with-colons", u).stdout.splitlines() if ln.startswith("fpr:")][0]
    fo, fa = fpr("official"), fpr("attacker")
    g("--quick-add-key", fo, "ed25519", "sign", "never")   # 공식 키에는 서명용 하위 키가 붙는다(Docker 키 구조와 같음)
    exp = lambda u: g("--armor", "--export", u).stdout.encode()  # noqa: E731
    dockerctl.KEY_FPR = fo.upper()
    w = os.path.join(TMP, "w"); os.makedirs(w)
    ok, why = dockerctl.key_check(exp("official"), w)
    check("공식 주 키 하나(+하위 키)는 통과", ok, why)
    ok, why = dockerctl.key_check(exp("official") + exp("attacker"), w)
    check("공식 키에 공격자 키를 하나 더 붙인 파일은 거부(주 키가 둘)", not ok and "2개" in why, why)
    ok, why = dockerctl.key_check(exp("attacker"), w)
    check("다른 지문의 키는 거부", not ok and "공식 값이 아닙니다" in why, why)
    ok, why = dockerctl.key_check(b"not a key", w)
    check("키가 아닌 내용은 거부", not ok, why)
else:
    print("  (건너뜀: gpg·nix 없음 — 키 규칙 시험 4건)")

shutil.rmtree(TMP, ignore_errors=True)
print(f"sbox-dockerctl {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
