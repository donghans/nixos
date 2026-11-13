#!/usr/bin/env python3
"""nixstrap 의 LUKS 헤더 백업 질문 흐름(luks_offer_header_backup) 시험 — 실제 cryptsetup 으로 파일 이미지에 백업한다.
cryptsetup 이 없으면 건너뜀. 실행: nix shell nixpkgs#cryptsetup -c python3 -I core/scripts/tests/test_nixstrap_backup.py"""
import glob, os, shutil, subprocess, sys, tempfile

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


if shutil.which("cryptsetup") is None:
    print("cryptsetup 없음 — 건너뜀"); sys.exit(0)

tmp = tempfile.mkdtemp()
img = os.path.join(tmp, "d.img"); open(img, "wb").truncate(64 * 1024 * 1024)
subprocess.run(["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode", "--pbkdf", "pbkdf2", "--pbkdf-force-iterations", "1000", "--key-file=-", img], input=b"x y z", check=True, capture_output=True)
shim = os.path.join(tmp, "shim"); os.makedirs(shim)
for name, body in {
    "lsblk": 'echo "/dev/sdb1 57G exfat Ventoy 1"; echo "/dev/sdb2 32M vfat VTOYEFI 1"; echo "/dev/nvme0n1p2 900G crypto_LUKS  0"',
    "mount": 'echo "$@" >> "$CALLS"',
    "umount": 'echo "umount $@" >> "$CALLS"',
    "sync": "true",
    "scp": 'echo "scp $@" >> "$CALLS"',
}.items():
    p = os.path.join(shim, name); open(p, "w").write("#!/usr/bin/env bash\n" + body + "\n"); os.chmod(p, 0o755)
calls = os.path.join(tmp, "calls.txt")


def run(pick, stdin):
    open(calls, "w").close()
    for d in glob.glob("/tmp/luks-hdr-mnt-*") + glob.glob("/tmp/luks-hdr-??????"):
        shutil.rmtree(d, ignore_errors=True)
    drv = f'''
set -u
SCRIPT_DIR="{SCRIPTS}"
source "$SCRIPT_DIR/nixstrap.lib-ui.sh"
source "$SCRIPT_DIR/nixstrap.lib-luks.sh"
_pick() {{ REPLY={pick}; }}
luks_offer_header_backup "{img}"; echo "RC=$?"
'''
    env = {"PATH": shim + ":" + os.environ["PATH"], "CALLS": calls, "LC_ALL": "C.UTF-8"}
    r = subprocess.run(["bash", "-c", drv], capture_output=True, text=True, input=stdin, env=env)
    return r.stdout + r.stderr


# 아니오 → 건너뜀, 아무것도 안 함
o = run(0, "n\n"); check("n → 건너뜀", "RC=0" in o and "백업 건너뜀" in o and open(calls).read() == "", o)

# USB 파티션(0번: Ventoy exfat) 선택 → 마운트 → 백업 → umount
o = run(0, "\n")
c = open(calls).read()
check("USB 선택: 후보에 Ventoy 파티션만(LUKS 내장 디스크 제외) 마운트", "/dev/sdb1" in c.split()[0] if c else False, c)
mnts = glob.glob("/tmp/luks-hdr-mnt-*")
check("USB 선택: 백업 성공 메시지", "헤더 백업 완료" in o and "RC=0" in o, o[-400:])
check("USB 선택: 마운트 지점에 헤더 파일", bool(mnts) and bool(glob.glob(mnts[0] + "/luks-header-*.img")), str(mnts))
check("USB 선택: umount 호출", "umount" in c, c)
check("슬롯 변경 후 재백업 안내", "다시 백업" in o)

# 직접 경로(후보 3개 중 인덱스 2 = '+ 이미 마운트된 디렉터리': lsblk 후보는 hotplug 2개)
dest = os.path.join(tmp, "dest"); os.makedirs(dest)
o = run(2, "\n" + dest + "\n")
check("경로 입력: 백업 성공", "헤더 백업 완료" in o and bool(glob.glob(dest + "/luks-header-*.img")), o[-400:])
# 잘못된 경로 → 실패 → 재시도 안 함(n) → 계속 진행(RC=0)
o = run(2, "\n/nonexistent\nn\n")
check("경로 오류 + 재시도 거부 → 경고 후 계속(RC=0)", "RC=0" in o and "백업하지 않고 계속" in o, o[-400:])
# scp 선택(인덱스 3)
o = run(3, "\nme@host:/bk/\n")
check("scp: 대상으로 전송 호출", "scp" in open(calls).read() and "me@host:/bk/" in open(calls).read(), open(calls).read())
# 건너뜀(인덱스 4)
o = run(4, "\n"); check("메뉴 '건너뜀'", "RC=0" in o and "백업 건너뜀" in o)

for d in glob.glob("/tmp/luks-hdr-mnt-*") + glob.glob("/tmp/luks-hdr-??????"):
    shutil.rmtree(d, ignore_errors=True)
shutil.rmtree(tmp, ignore_errors=True)
print(f"\nnixstrap-backup {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
