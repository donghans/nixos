#!/usr/bin/env python3
"""nixstrap Phase 2(디스크 단계) 명령 시퀀스 시험 — 외부 명령을 가짜 실행 파일로 바꿔 호출 인자를 기록한다.
  - LUKS=false(기본) 시나리오 4개는 golden/*.txt (LUKS 코드를 넣기 전 기록)와 **바이트 단위로 같아야** 한다.
  - LUKS=true 시나리오는 암호화 계층이 끼는 순서와 가드를 검사한다.
실행: python3 -I core/scripts/tests/test_nixstrap_phase2.py [--update-golden]"""
import os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
GOLD = os.path.join(HERE, "golden")
UPDATE = "--update-golden" in sys.argv
n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


tmp = tempfile.mkdtemp()
shim = os.path.join(tmp, "shim"); os.makedirs(shim)
log = os.path.join(tmp, "calls.txt")
repo = os.path.join(tmp, "repo"); os.makedirs(os.path.join(repo, "hosts"))
open(os.path.join(repo, "hosts", "_base.toml"), "w").write('username = "u"\n')
open(os.path.join(repo, "hosts", "h1.toml"), "w").write('type = "laptop"\npreset = "workstation"\n')

for name in ["parted", "mkfs.fat", "mkfs.btrfs", "mount", "umount", "btrfs", "swapoff", "udevadm", "mkdir", "cryptsetup", "cd_"]:
    p = os.path.join(shim, name)
    open(p, "w").write('#!/usr/bin/env bash\nprintf "%s" "$(basename "$0")" >> "$CALLS"\n'
                       'for a in "$@"; do printf " %s" "$a" >> "$CALLS"; done; printf "\\n" >> "$CALLS"\n'
                       # cryptsetup luksFormat/open 은 stdin 을 비운다
                       '[ "$(basename "$0")" = cryptsetup ] && cat >/dev/null\n'
                       '[ -n "${FAILTEST:-}" ] && case "$*" in *--test-passphrase*) exit 1;; esac\nexit 0\n')
    os.chmod(p, 0o755)
p = os.path.join(shim, "mountpoint"); open(p, "w").write("#!/usr/bin/env bash\nexit 1\n"); os.chmod(p, 0o755)

STUBS = "_move_repo _create_host_profile _setup_ssh_pubkey _resolve_metadata _extract_username _prepare_build_dir _generate_hw_config _install_nixos _post_process _save_ssh_pem _commit_ssh_files"

SCEN = {
    "mode2-wipe": 'FIX_PART=2; _PART_MODE=2; _NEW_PARTITIONS=true; _WIPE=true; _DISK=/dev/nvme0n1; _PART_START=1MiB; _PART_END=100%; _BOOT_END=1025MiB; _NEW_BOOT_NUM=1; _NEW_ROOT_NUM=2; BOOT_PART=/dev/nvme0n1p1; ROOT_PART=/dev/nvme0n1p2; FORMAT_BOOT=y; FORMAT_ROOT=y; _PRESET=workstation',
    "mode2-free": '_PART_MODE=2; _NEW_PARTITIONS=true; _WIPE=false; _DISK=/dev/sda; _PART_START=100GiB; _PART_END=200GiB; _BOOT_END=101GiB; _NEW_BOOT_NUM=3; _NEW_ROOT_NUM=4; BOOT_PART=/dev/sda3; ROOT_PART=/dev/sda4; FORMAT_BOOT=y; FORMAT_ROOT=y; _PRESET=server',
    "mode1-format": '_PART_MODE=1; _NEW_PARTITIONS=false; BOOT_PART=/dev/vda1; ROOT_PART=/dev/vda2; FORMAT_BOOT=y; FORMAT_ROOT=y; _PRESET=workstation',
    "mode1-keep": '_PART_MODE=1; _NEW_PARTITIONS=false; BOOT_PART=/dev/vda1; ROOT_PART=/dev/vda2; FORMAT_BOOT=n; FORMAT_ROOT=n; _PRESET=workstation',
}


def run(name, extra="", pw=None, envx=None):
    open(log, "w").close()
    drv = f'''
set -u
SCRIPT_DIR="{SCRIPTS}"
source "$SCRIPT_DIR/nixstrap.lib-ui.sh"
source "$SCRIPT_DIR/nixstrap.lib-luks.sh"
source "$SCRIPT_DIR/nixstrap.task-install.sh"
REPO_TMP="{repo}"; HOST=h1; _HOST_IS_NEW=false; _HOST_TYPE=laptop; _IS_VM=false
{SCEN[name]}
{extra}
for f in {STUBS}; do eval "$f() {{ printf 'STUB %s\\n' $f >> \\"\\$CALLS\\"; }}"; done
cd() {{ :; }}
phase2_execute >{tmp}/out.txt 2>&1; echo "RC=$?"
'''
    env = {"PATH": shim + ":" + os.environ.get("PATH", ""), "CALLS": log, "LC_ALL": "C.UTF-8", **(envx or {})}
    r = subprocess.run(["bash", "-c", drv], env=env, capture_output=True, text=True, input=pw or "")
    return open(log).read(), r.stdout + r.stderr + open(os.path.join(tmp, 'out.txt')).read()


for name in SCEN:
    calls, out = run(name)
    g = os.path.join(GOLD, name + ".txt")
    if UPDATE:
        open(g, "w").write(calls)
    check(f"{name}: RC=0", "RC=0" in out, out[-200:])
    check(f"{name}: 시퀀스가 golden 과 동일(LUKS=false)", os.path.exists(g) and open(g).read() == calls,
          "golden 없음" if not os.path.exists(g) else "")
    check(f"{name}: LUKS 아니오 때 cryptsetup 불호출", "cryptsetup" not in calls)

# ── LUKS=true ──
inst = os.path.join(tmp, "inst"); os.makedirs(os.path.join(inst, "hosts"))
shutil.copy(os.path.join(repo, "hosts", "h1.toml"), os.path.join(inst, "hosts", "h1.toml"))
LUKS_X = f'_INSTALL_REPO_DIR={inst}; _LUKS=true; _LUKS_PW="correct horse battery staple one two three four"'
calls, out = run("mode2-wipe", LUKS_X, pw="typed words\n")
lines = calls.splitlines()
def idx(prefix):
    return next((i for i, l in enumerate(lines) if l.startswith(prefix)), -1)
check("LUKS: RC=0", "RC=0" in out, out[-600:])
check("LUKS: mkpart 이름이 cryptroot", any(l.startswith("parted") and "mkpart cryptroot" in l for l in lines), calls)
check("LUKS: 'mkpart primary' 는 없음", not any("mkpart primary" in l for l in lines))
check("LUKS: luksFormat 이 원래 루트 파티션에", any(l.startswith("cryptsetup luksFormat") and l.endswith("/dev/nvme0n1p2") for l in lines))
check("LUKS: open 이 cryptroot 로", any(l.startswith("cryptsetup open") and l.endswith("/dev/nvme0n1p2 cryptroot") for l in lines))
check("LUKS: mkfs.btrfs 는 매퍼 장치에", any(l.startswith("mkfs.btrfs") and l.endswith("/dev/mapper/cryptroot") for l in lines))
check("LUKS: mount 도 매퍼 장치", any(l.startswith("mount") and "/dev/mapper/cryptroot /mnt" in l for l in lines))
check("LUKS: 순서 mklabel < mkpart < luksFormat < mkfs.btrfs",
      -1 < idx("parted /dev/nvme0n1 --script mklabel") < idx("parted /dev/nvme0n1 --script mkpart ESP") < idx("cryptsetup luksFormat") < idx("mkfs.btrfs"), calls)
check("LUKS: ESP 는 LUKS 밖(mkfs.fat 이 원래 부트 파티션)", any(l.startswith("mkfs.fat") and l.endswith("/dev/nvme0n1p1") for l in lines))
check("LUKS: 열림 검증(--test-passphrase) 이 mkfs.btrfs 보다 앞", -1 < idx("cryptsetup open --test-passphrase") < idx("mkfs.btrfs"), calls)

import tomllib
t = tomllib.load(open(os.path.join(inst, "hosts", "h1.toml"), "rb"))
check("LUKS: 설치 사본 toml 에 mods.sys.services.luks = true", t.get("mods", {}).get("sys", {}).get("services", {}).get("luks") is True, str(t))
check("LUKS: 원본 저장소 toml 은 그대로", "luks" not in open(os.path.join(repo, "hosts", "h1.toml")).read())

# 열림 검증 실패 → mkfs 전에 중단
calls, out = run("mode2-wipe", LUKS_X, pw="a\nb\nc\n", envx={"FAILTEST": "1"})
check("검증 3회 실패 → mkfs.btrfs 없이 중단", "mkfs.btrfs" not in calls and "RC=0" not in out, calls[-200:])

# 시작 정리: 남은 매퍼를 mklabel 전에 닫는다 / LUKS 아니오면 닫지 않는다
md = os.path.join(tmp, "mapper"); os.makedirs(md); open(os.path.join(md, "cryptroot"), "w").close()
calls, out = run("mode2-wipe", LUKS_X + f"; _LUKS_MAPPER_DIR={md}", pw="typed\n")
ls = calls.splitlines()
check("LUKS: 남은 매퍼 close 가 mklabel 앞", "cryptsetup close cryptroot" in ls and ls.index("cryptsetup close cryptroot") < ls.index("parted /dev/nvme0n1 --script mklabel gpt"), calls[:300])
calls, out = run("mode2-wipe", f"_LUKS_MAPPER_DIR={md}")
check("LUKS 아니오: 열려 있는 cryptroot 를 닫지 않음", "cryptsetup" not in calls)
# 모드 1 에서 _LUKS=true 는 내부 정합성 오류로 거부
calls, out = run("mode1-format", LUKS_X, pw="x\n")
check("모드1 + LUKS 는 거부(포맷 전 중단)", "cryptsetup luksFormat" not in calls and "RC=0" not in out)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nnixstrap-phase2 {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
