#!/usr/bin/env python3
"""nixstrap Phase 1 입력(ask_luks·ask_laptop·validate_luks_state·save_params)과 신규 호스트 toml 생성 시험.
실행: python3 -I core/scripts/tests/test_nixstrap_phase1.py"""
import os, shutil, subprocess, sys, tempfile, tomllib

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


tmp = tempfile.mkdtemp()
repo = os.path.join(tmp, "repo"); os.makedirs(os.path.join(repo, "hosts"))
open(os.path.join(repo, "hosts", "_base.toml"), "w").write('username = "u"\n')
open(os.path.join(repo, "hosts", "plain.toml"), "w").write('type = "desktop"\npreset = "workstation"\n')
open(os.path.join(repo, "hosts", "enc.toml"), "w").write('type = "laptop"\npreset = "workstation"\n\n[mods.sys.services]\nrefind = true\nluks = true\n\n[mods.gui.apps]\nx = true\n')
open(os.path.join(repo, "hosts", "srv.toml"), "w").write('type = "server"\npreset = "server"\n')


def bash(setup, stdin=""):
    drv = f'''
set -u
SCRIPT_DIR="{SCRIPTS}"
source "$SCRIPT_DIR/nixstrap.lib-ui.sh"
source "$SCRIPT_DIR/nixstrap.lib-luks.sh"
source "$SCRIPT_DIR/nixstrap.task-input.sh"
source "$SCRIPT_DIR/nixstrap.task-install.sh"
REPO_TMP="{repo}"; _IS_VM=false; _HOST_IS_NEW=false; _LUKS=false; _IS_LAPTOP=false; _REFIND=false
_STATE_VERSION=""; _HOST_USERNAME=""; _SSH_ACCESS_MODE=""; _SSH_KEY_FILE=""; _SSH_KEY_GENERATED=false
PARAMS_FILE="{tmp}/params.env"; NIXOS_REPO=r/n; _HOST_PRESET_FROM_REPO=""; _BOOT_SIZE=""; _BOOT_END=""; _NEW_BOOT_NUM=""; _NEW_ROOT_NUM=""; _PART_START=""; _PART_END=""; BOOT_PART=""; ROOT_PART=""; FORMAT_BOOT=""; FORMAT_ROOT=""; _DISK=""
{setup}
'''
    r = subprocess.run(["bash", "-c", drv], capture_output=True, text=True, input=stdin, env={"PATH": os.environ["PATH"], "LC_ALL": "C.UTF-8"})
    return r.stdout + r.stderr


E1 = 'HOST=plain; _HOST_TYPE=desktop; _PRESET=workstation; _PART_MODE=2; _NEW_PARTITIONS=true; _WIPE=true;'
check("ask_luks y → true", "R=true" in bash(E1 + 'ask_luks; echo R=$_LUKS', "y\n"))
check("ask_luks Enter(기본) → false", "R=false" in bash(E1 + 'ask_luks; echo R=$_LUKS', "\n"))
check("서버는 묻지 않음", "R=false" in bash(E1.replace("desktop", "server").replace("workstation", "server") + 'ask_luks; echo R=$_LUKS', "y\n"))
check("모드 1 은 묻지 않음", "R=false" in bash(E1.replace("_PART_MODE=2", "_PART_MODE=1") + 'ask_luks; echo R=$_LUKS', "y\n"))
check("여유 공간 사용(_WIPE=false)은 묻지 않음", "R=false" in bash(E1.replace("_WIPE=true", "_WIPE=false") + 'ask_luks; echo R=$_LUKS', "y\n"))
check("VM 이면 안내", "필요 없습니다" in bash(E1 + '_IS_VM=true; ask_luks', "\n"))

# validate
ENC = 'HOST=enc; _HOST_TYPE=laptop; _PRESET=workstation; _PART_MODE=2; _NEW_PARTITIONS=true; _WIPE=true;'
check("toml luks=true 인데 아니오 → 오류", "RC=1" in bash(ENC + '_LUKS=false; validate_luks_state; echo RC=$?'))
check("toml luks=true 이고 예 → 통과", "RC=0" in bash(ENC + '_LUKS=true; validate_luks_state; echo RC=$?'))
check("toml luks 없음·아니오 → 통과", "RC=0" in bash(E1 + '_LUKS=false; validate_luks_state; echo RC=$?'))
check("모드 1 + _LUKS=true → 오류", "RC=1" in bash(E1.replace("_PART_MODE=2", "_PART_MODE=1") + '_LUKS=true; validate_luks_state; echo RC=$?'))
check("toml luks=true 인데 모드 1(자격 없음) → 오류", "RC=1" in bash(ENC.replace("_PART_MODE=2", "_PART_MODE=1") + '_LUKS=false; validate_luks_state; echo RC=$?'))

# laptop
NEWH = 'HOST=nh; _HOST_IS_NEW=true; '
o = bash(NEWH + '_PRESET=workstation; ask_laptop; echo R=$_IS_LAPTOP/$_REFIND', "y\n")
check("신규 노트북 y → laptop+refind", "R=true/true" in o, o)
check("신규 노트북 기본 → 아님", "R=false/false" in bash(NEWH + '_PRESET=workstation; ask_laptop; echo R=$_IS_LAPTOP/$_REFIND', "\n"))
check("신규 서버는 묻지 않음", "R=false/false" in bash(NEWH + '_PRESET=server; _IS_LAPTOP=true; ask_laptop; echo R=$_IS_LAPTOP/$_REFIND', "y\n"))
check("기존 호스트 toml 에서 refind·type 읽음", "R=true/true" in bash('HOST=enc; select_host_probe() { :; }; _HOST_TYPE=laptop; _IS_LAPTOP=true; _REFIND=$(python3 "$SCRIPT_DIR/nixstrap.lib-repo.py" mod-bool "$REPO_TMP" enc sys services refind); echo R=$_IS_LAPTOP/$_REFIND'))

# save_params: 선택은 저장, 암호는 저장 안 함
SENT = "sentinel-secret-words-zzz"
bash(E1 + f'_LUKS=true; _LUKS_PW="{SENT}"; _USER_PASSWORD="{SENT}"; _PART_MODE=2; save_params')
saved = open(os.path.join(tmp, "params.env")).read()
check("params 에 _LUKS=true 저장", "_LUKS=true" in saved)
check("params 에 복구 암호·로그인 암호 없음", SENT not in saved and "_LUKS_PW" not in saved)

# 신규 호스트 toml 생성 (laptop / VM+laptop / 평범)
def profile(extra):
    d = os.path.join(tmp, "inst"); shutil.rmtree(d, ignore_errors=True); os.makedirs(os.path.join(d, "hosts"))
    bash(f'_INSTALL_REPO_DIR={d}; HOST=nh; _PRESET=workstation; ' + extra + '; _create_host_profile >/dev/null')
    return tomllib.load(open(os.path.join(d, "hosts", "nh.toml"), "rb")), open(os.path.join(d, "hosts", "nh.toml")).read()


t, raw = profile("_IS_LAPTOP=true; _REFIND=true; _IS_VM=false")
check("laptop: type=laptop, refind=true", t["type"] == "laptop" and t["mods"]["sys"]["services"]["refind"] is True, raw)
t, raw = profile("_IS_LAPTOP=true; _REFIND=true; _IS_VM=true")
check("VM+laptop: 표 하나에 합쳐짐", raw.count("[mods.sys.services]") == 1 and t["mods"]["sys"]["services"]["incus-guest"] is True and t["mods"]["sys"]["services"]["refind"] is True, raw)
t, raw = profile("_IS_LAPTOP=false; _REFIND=false; _IS_VM=false")
check("평범한 신규: 기존과 같은 모양(type=desktop, 표 없음)", t["type"] == "desktop" and "mods" not in t, raw)
t, raw = profile("_IS_LAPTOP=false; _REFIND=false; _IS_VM=true")
check("VM 신규: 기존과 같은 모양", t["mods"]["sys"]["services"] == {"incus-guest": True, "incus": False}, raw)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nnixstrap-phase1 {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
