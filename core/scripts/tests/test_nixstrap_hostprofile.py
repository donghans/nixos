#!/usr/bin/env python3
"""nixstrap 의 _create_host_profile(신규 호스트 toml 생성) 시험 — VM·노트북·서버 조합.
회귀: VM 설치에서 incus 만 끄면 incus-win11·gui incus-vm 이 incus 를 요구해 평가 어서션이 실패했다(P4 리허설).
실행: python3 -I core/scripts/tests/test_nixstrap_hostprofile.py"""
import os, shutil, subprocess, sys, tempfile, tomllib

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


def make(preset, vm, laptop=False, refind=False):
    d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "hosts"))
    drv = f'''
set -euo pipefail
SCRIPT_DIR="{SCRIPTS}"
source "$SCRIPT_DIR/nixstrap.lib-ui.sh"
HOST=t1; _PRESET={preset}; _IS_VM={"true" if vm else "false"}; _IS_LAPTOP={"true" if laptop else "false"}; _REFIND={"true" if refind else "false"}
_STATE_VERSION=""; _HOST_USERNAME=""; _INSTALL_REPO_DIR="{d}"
eval "$(sed -n '/^_create_host_profile()/,/^}}/p' "$SCRIPT_DIR/nixstrap.task-install.sh")"
_create_host_profile
'''
    r = subprocess.run(["bash", "-c", drv], capture_output=True, text=True, env={"PATH": os.environ["PATH"], "LC_ALL": "C.UTF-8"})
    path = os.path.join(d, "hosts", "t1.toml")
    t = tomllib.load(open(path, "rb")) if os.path.exists(path) else None
    raw = open(path).read() if os.path.exists(path) else ""
    shutil.rmtree(d, ignore_errors=True)
    return r, t, raw


r, t, raw = make("workstation", vm=True)
svc = (t or {}).get("mods", {}).get("sys", {}).get("services", {})
check("VM+workstation: toml 이 파싱된다", t is not None, r.stderr + raw)
check("VM: incus=false, incus-guest=true", svc.get("incus") is False and svc.get("incus-guest") is True, str(svc))
check("VM: incus-win11=false (회귀)", svc.get("incus-win11") is False, str(svc))
check("VM+workstation: gui.apps.incus-vm=false (회귀)", t["mods"]["gui"]["apps"].get("incus-vm") is False, raw)

r, t, raw = make("server", vm=True)
check("VM+server: gui 표를 만들지 않는다", t is not None and "gui" not in t.get("mods", {}), raw)
check("VM+server: incus-win11=false", t["mods"]["sys"]["services"].get("incus-win11") is False, raw)

r, t, raw = make("workstation", vm=False, laptop=True, refind=True)
check("실기 노트북: refind=true, type=laptop", t["type"] == "laptop" and t["mods"]["sys"]["services"] == {"refind": True}, raw)
check("실기: gui·incus 항목을 건드리지 않는다", "gui" not in t["mods"] and "incus" not in t["mods"]["sys"]["services"], raw)

r, t, raw = make("workstation", vm=True, laptop=True, refind=True)
svc = t["mods"]["sys"]["services"]
check("VM+노트북: services 표가 하나로 합쳐진다(refind 와 incus 모두)", svc.get("refind") is True and svc.get("incus") is False and raw.count("[mods.sys.services]") == 1, raw)

r, t, raw = make("workstation", vm=False)
check("실기 데스크톱: services 표 없음", t is not None and "mods" not in t, raw)

print(f"{n['ok']} ok, {n['bad']} bad")
sys.exit(1 if n["bad"] else 0)
