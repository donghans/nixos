#!/usr/bin/env python3
"""nixstrap 의 LUKS 헤더 백업 질문 흐름(luks_offer_header_backup) 시험 — 실제 cryptsetup 으로 파일 이미지에 백업한다.
cryptsetup 이 없으면 건너뜀. 실행: nix shell nixpkgs#cryptsetup -c python3 -I core/scripts/tests/test_nixstrap_backup.py"""
import glob, json, os, shutil, subprocess, sys, tempfile

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
    # 설치 대상 디스크(/dev/nvme0n1)가 USB 인 경우를 흉내내 그 ESP 도 hotplug 로 보이게 한다(후보에서 빠져야 함).
    # /dev/sdc1 은 레이블이 없는 USB(예전 파서가 빠뜨리던 경우).
    "lsblk": 'case "$*" in *lJ*) cat "$LSBLK_JSON";; *PKNAME*) echo /dev/nvme0n1;; esac',
    "mount": 'echo "$@" >> "$CALLS"',
    "umount": 'echo "umount $@" >> "$CALLS"',
    "sync": "true",
    "scp": 'echo "scp $@" >> "$CALLS"',
}.items():
    p = os.path.join(shim, name); open(p, "w").write("#!/usr/bin/env bash\n" + body + "\n"); os.chmod(p, 0o755)
calls = os.path.join(tmp, "calls.txt"); opts = os.path.join(tmp, "opts.txt")
lsblk_json = os.path.join(tmp, "lsblk.json")
open(lsblk_json, "w").write(json.dumps({"blockdevices": [
    {"name": "/dev/sdb1", "size": "57G", "fstype": "exfat", "label": "Ventoy", "hotplug": True, "pkname": "/dev/sdb"},
    {"name": "/dev/sdb2", "size": "32M", "fstype": "vfat", "label": "VTOYEFI", "hotplug": True, "pkname": "/dev/sdb"},
    {"name": "/dev/sdc1", "size": "14G", "fstype": "exfat", "label": None, "hotplug": True, "pkname": "/dev/sdc"},
    {"name": "/dev/nvme0n1p1", "size": "1G", "fstype": "vfat", "label": "ESP", "hotplug": True, "pkname": "/dev/nvme0n1"},
    {"name": "/dev/nvme0n1p2", "size": "900G", "fstype": "crypto_LUKS", "label": None, "hotplug": False, "pkname": "/dev/nvme0n1"}]}))


def run(pick, stdin):
    open(calls, "w").close()
    for d in glob.glob("/tmp/luks-hdr-mnt-*") + glob.glob("/tmp/luks-hdr-??????"):
        shutil.rmtree(d, ignore_errors=True)
    drv = f'''
set -u
SCRIPT_DIR="{SCRIPTS}"
source "$SCRIPT_DIR/nixstrap.lib-ui.sh"
source "$SCRIPT_DIR/nixstrap.lib-luks.sh"
_pick() {{ printf '%s\\n' "${{@:2}}" > "$OPTS"; REPLY={pick}; }}
luks_offer_header_backup "{img}"; echo "RC=$?"
'''
    env = {"PATH": shim + ":" + os.environ["PATH"], "CALLS": calls, "OPTS": opts, "LSBLK_JSON": lsblk_json, "LC_ALL": "C.UTF-8"}
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

# 후보 목록: 레이블 없는 USB 포함, 설치 대상 디스크 자신의 파티션·LUKS 파티션은 제외
shown = open(opts).read()
check("후보에 레이블 없는 USB(/dev/sdc1)가 있다(회귀)", "/dev/sdc1" in shown and "<레이블 없음>" in shown, shown)
check("후보에 설치 대상 디스크의 파티션이 없다(회귀)", "nvme0n1" not in shown, shown)
check("후보에 Ventoy 파티션이 있다", "/dev/sdb1" in shown and "Ventoy" in shown, shown)

# 직접 경로(후보 3개 다음 인덱스 3 = '+ 이미 마운트된 디렉터리')
dest = os.path.join(tmp, "dest"); os.makedirs(dest)
o = run(3, "\n" + dest + "\n")
check("경로 입력: 백업 성공", "헤더 백업 완료" in o and bool(glob.glob(dest + "/luks-header-*.img")), o[-400:])
# 잘못된 경로 → 실패 → 재시도 안 함(n) → 계속 진행(RC=0)
o = run(3, "\n/nonexistent\nn\n")
check("경로 오류 + 재시도 거부 → 경고 후 계속(RC=0)", "RC=0" in o and "백업하지 않고 계속" in o, o[-400:])
# scp 선택(인덱스 4)
o = run(4, "\nme@host:/bk/\n")
check("scp: 대상으로 전송 호출(옵션 종료 -- 포함)", "scp -- " in open(calls).read() and "me@host:/bk/" in open(calls).read(), open(calls).read())
# 건너뜀(인덱스 5)
o = run(5, "\n"); check("메뉴 '건너뜀'", "RC=0" in o and "백업 건너뜀" in o)

for d in glob.glob("/tmp/luks-hdr-mnt-*") + glob.glob("/tmp/luks-hdr-??????"):
    shutil.rmtree(d, ignore_errors=True)
shutil.rmtree(tmp, ignore_errors=True)
print(f"\nnixstrap-backup {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
