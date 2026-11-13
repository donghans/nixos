#!/usr/bin/env python3
"""nixstrap.lib-repo.py 의 mod-bool·set-mod-bool 시험 (실제 hosts/msi-summit-me.toml 모양 포함).
실행: python3 -I core/scripts/tests/test_nixstrap_repo.py"""
import os, subprocess, sys, tempfile, tomllib

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(SCRIPTS, "nixstrap.lib-repo.py")
n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


def py(*a):
    return subprocess.run([sys.executable, "-I", LIB, *a], capture_output=True, text=True)


tmp = tempfile.mkdtemp()


def mk(text):
    p = os.path.join(tmp, "h.toml"); open(p, "w").write(text); return p


def val(p):
    return tomllib.load(open(p, "rb")).get("mods", {}).get("sys", {}).get("services", {}).get("luks")


# 실제 모양: services 표 뒤에 gui.apps 표가 있고 파일이 gui 표로 끝난다
MSI = 'type = "laptop"\npreset = "workstation"\n\n[mods.sys.services]\nrefind = true\nembedctl = true\n\n[mods.gui.apps]\nfoo = true\n'
p = mk(MSI); r = py("set-mod-bool", p, "sys", "services", "luks", "true")
check("삽입 성공", r.returncode == 0, r.stderr)
check("luks 가 sys.services 에 들어감", val(p) is True)
check("gui.apps 에는 안 들어감", "luks" not in tomllib.load(open(p, "rb"))["mods"]["gui"]["apps"])
check("기존 키 보존", tomllib.load(open(p, "rb"))["mods"]["sys"]["services"]["refind"] is True)

p = mk(MSI.replace("embedctl = true\n", "embedctl = true\nluks = false\n")); py("set-mod-bool", p, "sys", "services", "luks", "true")
check("luks=false 교체", val(p) is True and open(p).read().count("luks") == 1)

p = mk('type = "desktop"\npreset = "workstation"\n'); r = py("set-mod-bool", p, "sys", "services", "luks", "true")
check("표가 없으면 새로 만듦", r.returncode == 0 and val(p) is True)

p = mk('type = "desktop"\npreset = "workstation"\n\n[mods.sys.services]\nincus-guest = true\nincus = false\n'); py("set-mod-bool", p, "sys", "services", "luks", "true")
check("VM 호스트 표에 합쳐짐", val(p) is True and open(p).read().count("[mods.sys.services]") == 1)

p = mk(MSI + "\n# 주석\n"); py("set-mod-bool", p, "sys", "services", "refind", "false")
check("다른 키(refind) 교체", tomllib.load(open(p, "rb"))["mods"]["sys"]["services"]["refind"] is False)
check("잘못된 값 거부", py("set-mod-bool", p, "sys", "services", "luks", "yes").returncode == 1)

repo = os.path.join(tmp, "repo"); os.makedirs(os.path.join(repo, "hosts"))
open(os.path.join(repo, "hosts", "a.toml"), "w").write(MSI)
check("mod-bool true", py("mod-bool", repo, "a", "sys", "services", "refind").stdout.strip() == "true")
check("mod-bool 없는 키 false", py("mod-bool", repo, "a", "sys", "services", "luks").stdout.strip() == "false")
check("mod-bool 없는 호스트 false", py("mod-bool", repo, "zz", "sys", "services", "luks").stdout.strip() == "false")

print(f"\nnixstrap-repo {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
