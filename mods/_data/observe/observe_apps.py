"""observe_apps — 프로세스를 **앱 단위**로 묶는 규칙(순수 계산). Netdata 의 앱 그룹 개념을 우리 시스템에 맞게 가져온 것: 저장은 앱별 합계 + '(기타)' 로 해서 전체 프로세스가 빠짐없이 들어간다
(옛 방식은 표본마다 상위 16행만 저장해 전체 CPU 의 약 60%·문맥 전환의 약 34%만 담았다).
규칙: ① 커널 스레드(부모가 kthreadd, 실행 파일 없음) → `kernel` ② 이름(실행 파일 또는 comm)을 정리(앞의 `.`, 뒤의 `-wrapped`·`-wrapper` 제거)한 뒤 RULES 의 첫 일치
③ Electron 계열은 모든 도우미(zygote·renderer·gpu)를 **맨 위 electron 프로세스의 `app.asar` 경로(Nix 저장소 이름)**로 묶어 앱 이름을 정한다(예: bitwarden-desktop) — 명령줄 중 asar 경로만 보고 저장하지 않는다
④ 그 밖에는 정리한 이름 그대로. 개인정보: 앱 이름(프로세스 이름)과 수치 합계만."""
from __future__ import annotations

import re

KERNEL = "kernel"
OTHER = "(기타)"
# (정리한 이름에 대한 정규식, 앱 이름) — 위에서부터 첫 일치. 정리한 이름은 소문자.
RULES = [
    (r"^claude", "claude"),
    (r"^(netdata|go\.d\.plugin|apps\.plugin|debugfs\.plugin|otel-plugin|nfacct|ioping|cgroup-network|ebpf\.plugin|network-viewer)", "netdata"),
    (r"^vivaldi", "vivaldi"),
    (r"^(nix$|nix-|nixos-rebuild|nixup|nom$)", "nix"),
    (r"^(hyprland|start-hyprland|hyprctl|hypridle|hyprlock|hyprpaper|hyprcursor|uwsm)", "hyprland"),
    (r"^(kitty|kitten)", "kitty"),
    (r"^tailscaled", "tailscaled"),
    (r"^waybar", "waybar"),
]


def clean_name(name):
    """Nix 래퍼 이름 정리: `.claude-wrapped` → `claude`, `.Hyprland-wrapp` → `hyprland`(comm 이 15자로 잘린 경우 포함). 소문자."""
    n = (name or "").strip().lstrip(".")
    n = re.sub(r"(-wrapped)+$|-wrapper$|-wrapp$|-wrappe$|-wrap$", "", n, flags=re.I)
    return n.lower()


def asar_app_name(args):
    """명령줄 인자 목록에서 app.asar 경로를 찾아 앱 이름(Nix 저장소 이름에서 버전 제거)을 돌려준다. 못 찾으면 None."""
    for a in args:
        if a.endswith("app.asar"):
            m = re.search(r"/nix/store/[a-z0-9]{32}-([^/]+)/", a)
            if m:
                return re.sub(r"-v?\d[\w.]*$", "", m.group(1)) or m.group(1)
            parts = [p for p in a.split("/") if p]
            if "resources" in parts and parts.index("resources") > 0:
                return parts[parts.index("resources") - 1].lower()
    return None


def app_name(pid, comm, exe, ppid, exe_of, ppid_of, read_cmdline, root_cache):
    """한 프로세스의 앱 이름. exe_of/ppid_of 는 이번 표본의 pid→값, read_cmdline(pid)→인자 목록, root_cache 는 electron 루트 pid→앱 이름 캐시."""
    if not exe and (ppid == 2 or pid == 2):
        return KERNEL
    name = clean_name(exe or comm)
    if name == "electron" or (exe == "electron"):
        root, seen = pid, set()
        while exe_of.get(ppid_of.get(root)) == "electron" and root not in seen:
            seen.add(root)
            root = ppid_of[root]
        if root not in root_cache:
            try:
                root_cache[root] = asar_app_name(read_cmdline(root)) or "electron"
            except OSError:
                root_cache[root] = "electron"
        return root_cache[root]
    for rx, app in RULES:
        if re.match(rx, name):
            return app
    return name or comm or "?"


class AppResolver:
    """pid → 앱 이름 캐시(같은 pid·이름이면 재사용). electron 루트의 명령줄은 루트마다 한 번만 읽는다."""

    def __init__(self, limit=8192):
        self.cache, self.roots, self.limit = {}, {}, limit

    def resolve(self, pid, comm, exe, ppid, exe_of, ppid_of, read_cmdline):
        key = (comm, exe, ppid)
        c = self.cache.get(pid)
        if c and c[0] == key:
            return c[1]
        app = app_name(pid, comm, exe, ppid, exe_of, ppid_of, read_cmdline, self.roots)
        if len(self.cache) > self.limit:
            self.cache.clear()
        self.cache[pid] = (key, app)
        return app


def aggregate(rows, top=24):
    """앱별 합계 행(dict: app, n, cpu_core_pct, ctxsw_vol_s, rss_mb)을 CPU·전환 큰 순으로 top 개만 남기고 나머지는 '(기타)' 한 행으로 합친다 — 합계는 빠짐없이 보존."""
    live = [r for r in rows if r["cpu_core_pct"] > 0 or r["ctxsw_vol_s"] > 0.5]
    live.sort(key=lambda r: -(r["cpu_core_pct"] + r["ctxsw_vol_s"] / 100))
    head, tail = live[:top], live[top:]
    if tail:
        head.append({"app": OTHER, "n": sum(r["n"] for r in tail), "cpu_core_pct": round(sum(r["cpu_core_pct"] for r in tail), 2),
                     "ctxsw_vol_s": round(sum(r["ctxsw_vol_s"] for r in tail), 1), "rss_mb": round(sum(r["rss_mb"] for r in tail), 1)})
    return head
