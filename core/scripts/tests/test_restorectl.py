#!/usr/bin/env python3
"""restorectl.sh 시험 — 가짜 번들(실제와 같은 SHA256SUMS 형식)·가짜 HOME 으로 fetch/verify/extract/pick/clean.
scp·ssh-copy-id 를 쓰는 fetch(원격)·key 는 시험하지 않는다(--from-dir 로 대체). zstd 가 없으면 건너뜀.
실행: nix shell nixpkgs#zstd -c python3 -I core/scripts/tests/test_restorectl.py"""
import hashlib, os, shutil, subprocess, sys, tempfile

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "restorectl.sh")
n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


if not shutil.which("zstd"):
    print("zstd 없음 — 건너뜀"); sys.exit(0)

tmp = tempfile.mkdtemp()
src = os.path.join(tmp, "bundle-src"); os.makedirs(src)
home = os.path.join(tmp, "home"); os.makedirs(home)
stage = os.path.join(tmp, "stage")


def mk(name, files):
    root = os.path.join(tmp, "root-" + name); shutil.rmtree(root, ignore_errors=True)
    for rel, content in files.items():
        p = os.path.join(root, rel); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").write(content)
    subprocess.run(f"tar -C '{root}' -cf - . | zstd -q -o '{src}/{name}.tar.zst'", shell=True, check=True)


mk("linux-home", {".ssh/config": "OLDCONFIG", ".ssh/id_ed25519": "OLDKEY", ".claude/settings.json": "{}", ".claude/projects/x/y.jsonl": "BIG",
                  ".local/share/nix-secrets/a.age.key": "AGE", ".config/Bitwarden/d": "BW", "Downloads/doc.txt": "DOC"})
mk("windows", {"Documents/resume.pdf": "PDF"})
mk("system-root", {"etc/ssh/ssh_host_ed25519_key": "HK"})
for f in ("MANIFEST-linux.txt", "MANIFEST-windows.txt"):
    open(os.path.join(src, f), "w").write("x\n")
sums = "# 시험용 번들\n" + "".join(f"{t}.tar.zst {hashlib.sha256(open(os.path.join(src, t + '.tar.zst'), 'rb').read()).hexdigest()}\n" for t in ("linux-home", "windows", "system-root"))
open(os.path.join(src, "SHA256SUMS.txt"), "w").write(sums)

env = {"PATH": os.environ["PATH"], "HOME": home, "LC_ALL": "C.UTF-8"}


def run(*args, stdin=""):
    r = subprocess.run(["bash", SCRIPT, *args, "--stage", stage], capture_output=True, text=True, input=stdin, env=env)
    return r.returncode, r.stdout + r.stderr


rc, o = run("fetch", "--from-dir", src)
check("fetch + 무결성(실제 형식의 SHA256SUMS)", rc == 0 and "무결성 확인됨" in o, o)
check("임시 폴더 권한 700", oct(os.stat(stage).st_mode & 0o777) == "0o700", oct(os.stat(stage).st_mode))

# 변조 → 실패하고 풀지 않는다
open(os.path.join(stage, "bundle", "windows.tar.zst"), "ab").write(b"x")
rc, o = run("verify"); check("변조된 번들은 verify 실패", rc != 0 and "실패" in o, o)
rc, o = run("extract"); check("변조된 번들은 extract 도 거부(풀기 전 검증)", rc != 0 and not os.path.exists(os.path.join(stage, "extracted", "windows")), o)
shutil.copy(os.path.join(src, "windows.tar.zst"), os.path.join(stage, "bundle", "windows.tar.zst"))

# 항목이 3개 미만인 SHA256SUMS 는 거부
good = open(os.path.join(stage, "bundle", "SHA256SUMS.txt")).read()
open(os.path.join(stage, "bundle", "SHA256SUMS.txt"), "w").write("\n".join(good.splitlines()[:2]) + "\n")
rc, o = run("verify"); check("검사 항목 3개 미만이면 거부(번들 일부만 검사하는 사고 방지)", rc != 0 and "3개 미만" in o, o)
open(os.path.join(stage, "bundle", "SHA256SUMS.txt"), "w").write(good)

rc, o = run("extract")
check("extract: 3개 폴더로 풀림", rc == 0 and os.path.exists(os.path.join(stage, "extracted", "home", ".ssh", "config")) and os.path.exists(os.path.join(stage, "extracted", "windows", "Documents", "resume.pdf")) and os.path.exists(os.path.join(stage, "extracted", "system-root", "etc", "ssh", "ssh_host_ed25519_key")), o)
check("extract 는 HOME 을 건드리지 않음", os.listdir(home) == [], str(os.listdir(home)))

# pick: 새로 만든 키는 보존, 옛 설정은 추가, 기본 목록 밖(Downloads·claude projects)은 복사하지 않음
os.makedirs(os.path.join(home, ".ssh")); open(os.path.join(home, ".ssh", "id_ed25519"), "w").write("NEWKEY"); os.chmod(os.path.join(home, ".ssh"), 0o755)
rc, o = run("pick", "--yes")
read = lambda p: open(os.path.join(home, p)).read() if os.path.exists(os.path.join(home, p)) else None
check("pick: 기존 키는 덮어쓰지 않음", read(".ssh/id_ed25519") == "NEWKEY", o)
check("pick: 옛 ssh config 는 추가됨", read(".ssh/config") == "OLDCONFIG", o)
check("pick: nix-secrets·Bitwarden·settings.json 복사", read(".local/share/nix-secrets/a.age.key") == "AGE" and read(".config/Bitwarden/d") == "BW" and read(".claude/settings.json") == "{}", o)
check("pick: .ssh 중첩 복사 없음(.ssh/.ssh)", not os.path.exists(os.path.join(home, ".ssh", ".ssh")))
check("pick: 기본 목록 밖은 복사하지 않음(claude projects·Downloads)", read(".claude/projects/x/y.jsonl") is None and read("Downloads/doc.txt") is None)
check("pick: .ssh 권한 700", oct(os.stat(os.path.join(home, ".ssh")).st_mode & 0o777) == "0o700")

rc, o = run("pick", "--yes", "Downloads/doc.txt", "../etc/passwd")
check("pick: 직접 지정 경로는 복사, .. 경로는 거부", rc != 0 and "상대 경로" in o or read("Downloads/doc.txt") == "DOC", o)
rc, o = run("pick", "--yes", "/etc/passwd"); check("pick: 절대 경로 거부", rc != 0 and "상대 경로" in o, o)
rc, o = run("pick", "nothing-here", stdin="y\n"); check("pick: 번들에 없는 항목은 건너뜀", rc == 0 and "번들에 없음" in o, o)
rc, o = run("pick", ".config/Bitwarden", stdin="n\n"); check("pick: 확인에서 n 이면 건너뜀", "건너뜀: .config/Bitwarden" in o, o)

rc, o = run("clean"); check("clean: 임시 폴더 삭제", rc == 0 and not os.path.exists(stage), o)
rc, o = run("bogus"); check("알 수 없는 명령은 오류", rc != 0, o)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nrestorectl {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
