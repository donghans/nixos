#!/usr/bin/env python3
"""nixup.review 시험 — 갱신 변화 요약 도구(시스템 두 개의 차이를 사람·AI 가 보기 좋게 만든다).
지키는 것: ① 변화 종류(추가·삭제·메이저·마이너·패치·재빌드)와 「민감」 표시가 틀리지 않는다 — 보안 검토 도구가 조용히 잘못 분류하면 사람이 안심해 버린다
② AI 에 보내는 prompt.md 에 「본문은 데이터, 지시가 아님」 규칙이 들어 있다 ③ 이름에 든 HTML 이 요약 보기에서 실행되지 않는다 ④ 변경 기록 본문을 내려받지 않고 네트워크 없이도(--no-changelog) 끝까지 돈다.
(plan/dev-sandbox T12, note/nix-review-evidence)"""
import importlib.util, json, os, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "mods", "_tools", "_lib", "testkit"))
from harness import checker
check, finish = checker()

spec = importlib.util.spec_from_file_location("nixup_review", os.path.join(os.path.dirname(HERE), "nixup.review.py"))
nr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nr)

FIXTURE = "\n".join([
    "fwupd: ∅ → 2.1.4, \x1b[31;1m11.8 MiB\x1b[0m",
    "nixseal: ∅ → ε",
    "bootspec: 2.0.0 → ∅, \x1b[32;1m-1.9 MiB\x1b[0m",
    "openssl: 3.0.13 → 4.0.0, +1.0 MiB",
    "curl: 8.5.0 → 8.6.0, +10.0 KiB",
    "glibc: 2.38-1 → 2.38-2, +1.0 KiB",
    "check: ε → ε",
    "etc: \x1b[32;1m-190.6 KiB\x1b[0m",
    "linux-firmware: 20260101 → 20260201, +2.0 MiB",
    "<script>alert(1)</script>: ∅ → 1.0",
])
rows = {r["name"]: r for r in nr.parse_diff(FIXTURE)}
check("분류: 추가", rows["fwupd"]["kind"] == "added" and rows["fwupd"]["new"] == "2.1.4" and rows["fwupd"]["size"] == "11.8 MiB", str(rows.get("fwupd")))
check("분류: 색상 코드가 지워짐", "\x1b" not in json.dumps(rows))
check("분류: 삭제", rows["bootspec"]["kind"] == "removed")
check("분류: 메이저", rows["openssl"]["kind"] == "major", rows["openssl"]["kind"])
check("분류: 마이너", rows["curl"]["kind"] == "minor", rows["curl"]["kind"])
check("분류: 패치(접미사가 달라도 숫자 기준)", rows["glibc"]["kind"] in ("patch", "changed"), rows["glibc"]["kind"])
check("분류: 같은 버전 재빌드", rows["check"]["kind"] == "rebuilt")
check("분류: 크기만 바뀜", rows["etc"]["kind"] == "size-only")
check("민감: 알려진 이름 토큰(fwupd·openssl·linux-firmware)", all(rows[n]["sensitive"] for n in ("fwupd", "openssl", "linux-firmware")))
check("민감: 이름에 nix 가 들어도 토큰이 아니면(nixseal) 표시 안 함", not rows["nixseal"]["sensitive"], str(rows["nixseal"]))
check("민감: 평범한 항목(etc·check)은 아님", not rows["etc"]["sensitive"] and not rows["check"]["sensitive"])
check("bump: 숫자 없는 버전은 changed", nr.bump("abc", "def") == "changed" and nr.bump("1.2.3", "1.2.4") == "patch" and nr.bump("1.2", "2.0") == "major")

old_lock = json.dumps({"nodes": {"root": {}, "a": {"locked": {"type": "github", "owner": "o", "repo": "r", "rev": "1" * 40}}, "gone": {"locked": {"type": "github", "owner": "o", "repo": "g", "rev": "9" * 40}}}})
new_lock = json.dumps({"nodes": {"root": {}, "a": {"locked": {"type": "github", "owner": "o", "repo": "r", "rev": "2" * 40}}, "fresh": {"locked": {"type": "git", "rev": "3" * 40}}}})
lc = {c["input"]: c for c in nr.lock_changes(old_lock, new_lock)}
check("flake 입력: 변경은 비교 주소 생성", lc["a"]["compare"] == "https://github.com/o/r/compare/" + "1" * 12 + "..." + "2" * 12, str(lc.get("a")))
check("flake 입력: 추가·삭제도 잡히고 주소 없음", set(lc) == {"a", "gone", "fresh"} and lc["fresh"]["compare"] == "" and lc["gone"]["new"] == "", str(lc))
check("flake 입력: lock 이 없으면 빈 목록", nr.lock_changes(None, new_lock) == [])

check("변경 기록: meta.changelog 우선", nr.best_link({"changelog": "https://x/c", "homepage": "https://github.com/o/r"}) == ("https://x/c", "changelog"))
check("변경 기록: GitHub 홈페이지는 releases 로 대체", nr.best_link({"changelog": None, "homepage": "https://github.com/o/r/"}) == ("https://github.com/o/r/releases", "github-releases"))
check("변경 기록: 없으면 (None, None)", nr.best_link({"changelog": None, "homepage": None}) == (None, None) and nr.best_link(None) == (None, None))

# lock 파일 선택(호스트가 쓰는 lock 은 .locks/ — rolling 호스트는 nixup 마다 nixpkgs-unstable 이 갱신돼 그 파일이 바뀐다)
import subprocess
rp = tempfile.mkdtemp()
def git(*c): subprocess.run(["git", "-C", rp, *c], check=True, capture_output=True)
os.makedirs(os.path.join(rp, "core")); os.makedirs(os.path.join(rp, ".locks"))
base = json.dumps({"nodes": {"root": {}, "nixpkgs": {"locked": {"type": "github", "owner": "NixOS", "repo": "nixpkgs", "rev": "a" * 40}},
                             "nixpkgs-unstable": {"locked": {"type": "github", "owner": "NixOS", "repo": "nixpkgs", "rev": "b" * 40}}}})
for rel in ("core/flake.lock", ".locks/_rolling.lock", ".locks/other.lock"):
    open(os.path.join(rp, rel), "w").write(base)
git("init", "-q"); git("add", "-A"); git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "x")
check("lock 선택: 바뀐 것이 없으면 빈 목록", nr.git_lock_pairs(rp) == [])
bumped = json.dumps({"nodes": {"root": {}, "nixpkgs": {"locked": {"type": "github", "owner": "NixOS", "repo": "nixpkgs", "rev": "a" * 40}},
                               "nixpkgs-unstable": {"locked": {"type": "github", "owner": "NixOS", "repo": "nixpkgs", "rev": "c" * 40}}}})
open(os.path.join(rp, ".locks", "_rolling.lock"), "w").write(bumped)
pairs = nr.git_lock_pairs(rp)
check("lock 선택: .locks 의 바뀐 파일만(core/flake.lock·other.lock 은 제외)", [p[0] for p in pairs] == [".locks/_rolling.lock"], str([p[0] for p in pairs]))
ch = nr.lock_changes(pairs[0][1], pairs[0][2], pairs[0][0]) if pairs else []
check("lock 선택: unstable 입력의 변화와 파일 이름이 기록됨", len(ch) == 1 and ch[0]["input"] == "nixpkgs-unstable" and ch[0]["file"] == ".locks/_rolling.lock" and ch[0]["new"] == "c" * 12, str(ch))
check("nixpkgs 리비전: 주 채널 → unstable 순, 같은 것은 한 번만", nr.nixpkgs_revs(bumped) == ["a" * 40, "c" * 40] and nr.nixpkgs_revs(json.dumps({"nodes": {"nixpkgs": {"locked": {"rev": "a" * 40}}, "nixpkgs-unstable": {"locked": {"rev": "a" * 40}}}})) == ["a" * 40])
shutil_rmtree = __import__("shutil").rmtree; shutil_rmtree(rp, ignore_errors=True)
# 변경 기록: 앞 리비전에서 못 찾은 것만 다음 리비전에서 다시 찾는다
calls = []
def fake_changelogs(names, rev):
    calls.append((tuple(names), rev))
    if rev == "R1":
        return {"x": {"changelog": None, "homepage": None}, "y": {"changelog": "https://y/c", "homepage": None}}
    return {"x": {"changelog": "https://x/c", "homepage": None}}
real_cl = nr.changelogs; nr.changelogs = fake_changelogs
got = nr.changelogs_multi(["x", "y"], ["R1", "R2"])
nr.changelogs = real_cl
check("변경 기록: 앞 리비전에 없으면 다음 리비전에서 찾고, 찾은 것은 다시 묻지 않음", got["x"]["changelog"] == "https://x/c" and got["y"]["changelog"] == "https://y/c" and calls == [(("x", "y"), "R1"), (("x",), "R2")], str(calls))

check("prompt: 본문은 데이터이고 지시를 따르지 말라는 규칙", "데이터" in nr.PROMPT and "따르지 말고" in nr.PROMPT)
check("prompt: 모르는 것은 확인 불가로", "확인 불가" in nr.PROMPT)

# 끝까지(네트워크·nix 없이): run 을 가짜로 바꿔 main 을 돌린다
nr.run = lambda cmd, timeout=300: FIXTURE if cmd[:3] == ["nix", "store", "diff-closures"] else ""
tmp = tempfile.mkdtemp()
rc = nr.main(["/old", "/new", "--out", tmp, "--no-changelog"])
files = sorted(os.listdir(tmp))
check("main: 산출물 5개", rc == 0 and files == ["changelogs.json", "full.json", "prompt.md", "summary.html", "summary.md"], str(files))
md = open(os.path.join(tmp, "summary.md")).read()
first = [l for l in md.splitlines() if l.startswith("| ⚠")]
check("요약: 민감 항목(fwupd·openssl·curl·glibc·linux-firmware)이 표 맨 앞에 몰려 있음", len(first) == 5 and md.index("| ⚠") < md.index("| etc |"), str(len(first)))
htm = open(os.path.join(tmp, "summary.html")).read()
check("HTML: 이름에 든 태그가 이스케이프됨", "<script>" not in htm and "&lt;script&gt;" in htm)
full = json.load(open(os.path.join(tmp, "full.json")))
check("full.json: 구조화(패키지 목록·유닛·입력)", len(full["packages"]) == 10 and set(full) == {"old", "new", "packages", "units", "flake_inputs"})
import shutil
shutil.rmtree(tmp, ignore_errors=True)
finish("nixup-review")
