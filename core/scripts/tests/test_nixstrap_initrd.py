#!/usr/bin/env python3
"""nixstrap 의 _luks_check_initrd 시험 — 실제 zstd+cpio 로 만든 initrd 를 먹인다.
회귀: 목록이 크면(수천 줄) `printf | grep -q` 가 pipefail 에서 SIGPIPE 로 실패해 있는 crypttab 을 없다고 오탐했다(P4 리허설).
zstd·cpio 가 없으면 건너뜀. 실행: nix shell nixpkgs#zstd nixpkgs#cpio -c python3 -I core/scripts/tests/test_nixstrap_initrd.py"""
import os, re, shutil, subprocess, sys, tempfile

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


if not (shutil.which("zstd") and shutil.which("cpio")):
    print("zstd/cpio 없음 — 건너뜀"); sys.exit(0)

tmp = tempfile.mkdtemp()


def make_initrd(dirname, files):
    """files: 상대 경로 목록(빈 파일). zstd 로 압축한 newc cpio 를 dirname 에 쓴다."""
    root = os.path.join(tmp, "root-" + os.path.basename(dirname))
    shutil.rmtree(root, ignore_errors=True)
    for f in files:
        p = os.path.join(root, f); os.makedirs(os.path.dirname(p), exist_ok=True); open(p, "w").close()
    os.makedirs(dirname, exist_ok=True)
    cpio = subprocess.run("find . | cpio -o -H newc 2>/dev/null | zstd -q", shell=True, cwd=root, capture_output=True, check=True).stdout
    open(os.path.join(dirname, "abc-initrd-linux-1-initrd.efi"), "wb").write(cpio)


def run(dirname):
    drv = f'''
set -euo pipefail
SCRIPT_DIR="{SCRIPTS}"
source "$SCRIPT_DIR/nixstrap.lib-ui.sh"
_LUKS=true; _INITRD_DIR="{dirname}"
eval "$(sed -n '/^_luks_check_initrd()/,/^}}/p' "$SCRIPT_DIR/nixstrap.task-install.sh")"
_luks_check_initrd; echo "RC=$?"
'''
    r = subprocess.run(["bash", "-c", drv], capture_output=True, text=True, env={"PATH": os.environ["PATH"], "LC_ALL": "C.UTF-8"})
    return re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr)


filler = [f"nix/store/h{i:05d}-lib/lib/libx{i}.so" for i in range(4000)]   # 큰 목록(SIGPIPE 재현 조건)

d = os.path.join(tmp, "big-with"); make_initrd(d, filler + ["etc/crypttab", "nix/store/hhh-cryptsetup-2.8/lib/libcryptsetup.so"])
out = run(d); check("큰 목록에서도 crypttab 을 찾는다(회귀)", "확인됨" in out and "Error" not in out, out)

d = os.path.join(tmp, "big-without"); make_initrd(d, filler)
out = run(d); check("큰 목록에 crypttab 이 없으면 Error", "Error" in out and "cryptsetup/crypttab 이 없습니다" in out, out)

d = os.path.join(tmp, "small-with"); make_initrd(d, ["etc/crypttab"])
out = run(d); check("작은 목록에서 찾는다", "확인됨" in out, out)

d = os.path.join(tmp, "empty"); os.makedirs(d)
out = run(d); check("initrd 가 없으면 Notice 로 건너뜀", "찾지 못해" in out and "Error" not in out, out)

d = os.path.join(tmp, "garbage"); os.makedirs(d); open(os.path.join(d, "x-initrd.efi"), "wb").write(b"not an archive")
out = run(d); check("해석 불가 형식은 Notice(확인 불가)", "해석하지 못했습니다" in out and "Error" not in out, out)

shutil.rmtree(tmp, ignore_errors=True)
print(f"{n['ok']} ok, {n['bad']} bad")
sys.exit(1 if n["bad"] else 0)
