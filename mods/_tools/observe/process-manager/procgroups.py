"""procgroups — 프로세스를 「뷰(view)」 단위로 그룹에 배정하는 규칙과 필터 식(순수 계산, 화면·신호 없음).

뷰 = 이름이 붙은 그룹핑 방식. 순서 있는 규칙 목록(첫 일치)과 기본 그룹(default)으로 정의한다.
  규칙 = {group: 그룹 이름, <조건>...}. 조건은 모두 AND, 리스트 값은 그 안에서 OR(이름은 fnmatch 글롭, 대소문자 무시).
  조건: kernel(bool) · uid("me"|"root"|"other"|숫자) · app/comm/exe(글롭 리스트) · cgroup(부분문자열 리스트) · session(bool, LLM 세션 트리 안)
        · ancestor_app(글롭 리스트: 조상 중 하나의 이름이 일치) · cpu_gt(%) · rss_gt("500M" 등)
  그룹 이름·default 에 쓰는 치환: @app · @comm · @unit(cgroup 유닛) · @session(LLM 세션 라벨).
사용자 확장: ~/.config/procui/groups.toml — [[view]] 로 새 뷰를 만들거나 같은 이름의 내장 뷰 **앞**에 규칙을 끼워 넣고, [protect] 로 보호 이름을 더한다.
명령 인자는 조건에 쓰지 않는다. 잘못된 설정은 그 항목만 버리고 경고 문자열을 돌려준다(앱이 죽지 않는다).
"""
from __future__ import annotations

import fnmatch
import os

import procscan as ps

try:
    import tomllib
except ImportError:  # python < 3.11
    tomllib = None

SESSION_COMMS = {".claude-wrapped", "claude", "codex", "gemini", "opencode"}   # hostmetrics.SESSION_COMMS 와 같은 목록
OTHER = "(기타)"
NO_SESSION = "(세션 밖)"
SIZES = {"k": 1 << 10, "m": 1 << 20, "g": 1 << 30}
CONDITIONS = {"kernel", "uid", "app", "comm", "exe", "cgroup", "session", "ancestor_app", "cpu_gt", "rss_gt"}

# 데스크톱 환경(컴포지터·패널·오디오·세션 버스 등) — 「내 환경」. 필요하면 groups.toml 로 앞에 규칙을 끼워 바꾼다.
DESKTOP = ["hyprland", "start-hyprland", "uwsm*", "waybar", "hypridle", "hyprlock", "hyprpaper", "hyprcursor", "swaync*", "pipewire*",
           "wireplumber", "dbus-*", "xdg-*", "gvfs*", "gnome-keyring*", "fcitx*", "ibus*", "polkit*", "systemd", "(sd-pam)"]
VM_CONTAINER = ["qemu-system*", "incusd", "incus*", "dockerd", "containerd*", "rootlesskit*", "docker*", "vfkit*"]

BUILTIN_VIEWS = [
    dict(name="소유", default=OTHER, rules=[
        dict(group="커널", kernel=True),
        dict(group="컨테이너·VM", app=VM_CONTAINER),
        dict(group="컨테이너·VM", comm=VM_CONTAINER),
        dict(group="컨테이너·VM", cgroup=["incus.service", "docker.service"]),
        dict(group="시스템", uid="other"),
        dict(group="내 환경", uid="me", app=DESKTOP),
        dict(group="내 환경", uid="me", comm=DESKTOP),
        dict(group="내 작업", uid="me"),
    ]),
    dict(name="앱", default="@app", rules=[]),
    dict(name="서비스", default="@unit", rules=[]),
    dict(name="세션", default="@session", rules=[]),
]


def parse_size(v):
    """'500M'·'2g'·'123' → 바이트. 형식이 틀리면 ValueError."""
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip().lower().rstrip("ib")
    if s and s[-1] in SIZES:
        return int(float(s[:-1]) * SIZES[s[-1]])
    return int(float(s))


class Ctx:
    """한 스냅샷에 대한 계산 상태: 내 UID, pid 맵, 프로세스별 LLM 세션 루트, 세션 이름."""

    def __init__(self, procs, me=None, session_names=None):
        self.procs = procs
        self.me = os.getuid() if me is None else me
        self.bp = ps.by_pid(procs)
        self.session_names = session_names or {}
        self._root = {}

    def session_root(self, pid):
        """pid 가 LLM 세션 프로세스이거나 그 자식 트리 안이면 세션 루트 pid(가장 가까운 조상), 아니면 None."""
        if pid in self._root:
            return self._root[pid]
        seen, x, res = [], pid, None
        while x and x in self.bp and x not in seen:
            if x in self._root:
                res = self._root[x]
                break
            seen.append(x)
            if self.bp[x]["comm"] in SESSION_COMMS:
                res = x
                break
            x = self.bp[x]["ppid"]
        for s in seen:
            self._root[s] = res
        return res

    def label(self, pid):
        r = self.session_root(pid)
        if r is None:
            return NO_SESSION
        return self.session_names.get(r) or f"{self.bp[r]['comm'].lstrip('.').replace('-wrapped', '')} #{r}"


def names(p):
    return {str(p.get(k, "")).lower() for k in ("comm", "exe", "app")} - {""}


def glob_any(p, pats):
    pats = [pats] if isinstance(pats, str) else pats
    ns = names(p)
    return any(fnmatch.fnmatchcase(n, str(g).lower()) for n in ns for g in pats)


def uid_match(p, want, ctx):
    if want == "me":
        return p["uid"] == ctx.me
    if want == "root":
        return p["uid"] == 0
    if want == "other":
        return p["uid"] != ctx.me
    return p["uid"] == int(want)


def rule_matches(rule, p, ctx):
    for k, v in rule.items():
        if k == "group":
            continue
        if k == "kernel":
            ok = bool(p["kernel"]) == bool(v)
        elif k == "uid":
            ok = uid_match(p, v, ctx)
        elif k in ("app", "comm", "exe"):
            pats = [v] if isinstance(v, str) else v
            ok = any(fnmatch.fnmatchcase(str(p.get(k, "")).lower(), str(g).lower()) for g in pats)
        elif k == "cgroup":
            ok = any(str(x) in p["cgroup"] for x in ([v] if isinstance(v, str) else v))
        elif k == "session":
            ok = (ctx.session_root(p["pid"]) is not None) == bool(v)
        elif k == "ancestor_app":
            x, ok, seen = p["ppid"], False, set()
            while x and x in ctx.bp and x not in seen:
                seen.add(x)
                if glob_any(ctx.bp[x], v):
                    ok = True
                    break
                x = ctx.bp[x]["ppid"]
        elif k == "cpu_gt":
            ok = p["cpu"] > float(v)
        elif k == "rss_gt":
            ok = p["rss"] > parse_size(v)
        else:
            ok = False
        if not ok:
            return False
    return True


def expand(template, p, ctx):
    return {"@app": p["app"], "@comm": p["comm"], "@unit": ps.unit_of(p["cgroup"]), "@session": ctx.label(p["pid"])}.get(template, template)


def classify(view, p, ctx):
    for rule in view["rules"]:
        if rule_matches(rule, p, ctx):
            return expand(rule["group"], p, ctx)
    return expand(view.get("default", OTHER), p, ctx)


# ---------- 사용자 설정 ----------
def validate_rule(rule):
    """(정상 규칙 | None, 경고). group 필수, 모르는 조건·형식 오류는 그 규칙을 버린다."""
    if not isinstance(rule, dict) or not isinstance(rule.get("group"), str) or not rule["group"]:
        return None, "규칙에 group 문자열이 없어 무시함"
    for k, v in rule.items():
        if k != "group" and k not in CONDITIONS:
            return None, f"규칙 '{rule['group']}': 모르는 조건 '{k}' — 무시함(가능: {', '.join(sorted(CONDITIONS))})"
        if k in ("app", "comm", "exe", "cgroup", "ancestor_app") and not (isinstance(v, str) or (isinstance(v, list) and all(isinstance(x, str) for x in v))):
            return None, f"규칙 '{rule['group']}': {k} 는 문자열 또는 문자열 리스트여야 함 — 무시함"
        try:
            if k == "rss_gt":
                parse_size(v)
            elif k == "cpu_gt":
                float(v)
            elif k == "uid" and v not in ("me", "root", "other"):
                int(v)
        except (ValueError, TypeError):
            return None, f"규칙 '{rule['group']}': {k}={v!r} 값을 읽을 수 없음 — 무시함"
    return rule, None


def load_config(path):
    """(추가 뷰 리스트, 보호 추가 {app·comm: 글롭 리스트}, 경고 리스트). 파일이 없으면 모두 비어 있고 경고도 없다."""
    warns, views, protect = [], [], {"app": [], "comm": []}
    if not path or not os.path.exists(path):
        return views, protect, warns
    if tomllib is None:
        return views, protect, ["이 파이썬에는 tomllib 이 없어 groups.toml 을 읽지 못함"]
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, ValueError) as e:
        return views, protect, [f"{path} 을 읽지 못함: {e}"]
    for v in data.get("view", []):
        if not isinstance(v, dict) or not isinstance(v.get("name"), str) or not v["name"]:
            warns.append("view 에 name 이 없어 무시함")
            continue
        rules = []
        for r in v.get("rule", []):
            ok, w = validate_rule(r)
            (rules.append(ok) if ok else warns.append(w))
        views.append(dict(name=v["name"], default=v.get("default") if isinstance(v.get("default"), str) else None, rules=rules))
    pr = data.get("protect", {})
    for k in ("app", "comm"):
        val = pr.get(k, []) if isinstance(pr, dict) else []
        if isinstance(val, str):
            val = [val]
        if isinstance(val, list) and all(isinstance(x, str) for x in val):
            protect[k] = list(val)
        else:
            warns.append(f"[protect] {k} 는 문자열 리스트여야 함 — 무시함")
    return views, protect, warns


def merge_views(builtin, extra):
    """같은 이름의 내장 뷰는 사용자 규칙을 **앞**에 끼우고(default 가 있으면 교체), 새 이름은 뒤에 붙인다."""
    out = [dict(v, rules=list(v["rules"])) for v in builtin]
    for e in extra:
        tgt = next((v for v in out if v["name"] == e["name"]), None)
        if tgt:
            tgt["rules"] = list(e["rules"]) + tgt["rules"]
            if e["default"]:
                tgt["default"] = e["default"]
        else:
            out.append(dict(name=e["name"], default=e["default"] or OTHER, rules=list(e["rules"])))
    return out


# ---------- 필터 식 ----------
def parse_filter(text):
    """'chrome cpu>50 mem>500M user:me group:빌드' → (pred(p, group) -> bool, 경고 리스트). 토큰은 모두 AND, 일반 단어는 이름·앱 부분일치(대소문자 무시)."""
    preds, warns = [], []
    for tok in (text or "").split():
        low = tok.lower()
        try:
            if low.startswith(("cpu>", "cpu<")):
                n = float(low[4:])
                preds.append((lambda n, gt: lambda p, g: (p["cpu"] > n) if gt else (p["cpu"] < n))(n, low[3] == ">"))
            elif low.startswith(("mem>", "mem<")):
                n = parse_size(low[4:])
                preds.append((lambda n, gt: lambda p, g: (p["rss"] > n) if gt else (p["rss"] < n))(n, low[3] == ">"))
            elif low.startswith("user:"):
                w = tok[5:]
                preds.append(lambda p, g, w=w: (p["uid"] == int(w)) if w.isdigit() else (p["uid"] == (0 if w == "root" else os.getuid())) if w in ("root", "me") else False)
            elif low.startswith("group:"):
                w = low[6:]
                preds.append(lambda p, g, w=w: w in g.lower())
            elif low.startswith("app:"):
                w = low[4:]
                preds.append(lambda p, g, w=w: w in p["app"].lower())
            elif low.startswith("pid:"):
                n = int(low[4:])
                preds.append(lambda p, g, n=n: p["pid"] == n)
            else:
                preds.append(lambda p, g, w=low: w in p["comm"].lower() or w in p["app"].lower() or w in p["exe"].lower())
        except ValueError:
            warns.append(f"필터 '{tok}' 를 읽을 수 없어 무시함")
    return (lambda p, g: all(f(p, g) for f in preds)), warns


# ---------- 그룹 만들기 ----------
SORTS = {"cpu": lambda g: (-g["cpu"], -g["rss"]), "mem": lambda g: (-g["rss"], -g["cpu"]), "n": lambda g: (-g["n"], g["name"]), "name": lambda g: g["name"].lower()}


def build_groups(procs, view, ctx, pred=None, sort="cpu"):
    """[{name, procs(CPU 큰 순), cpu, rss, n}] — 필터를 통과한 프로세스만. 모든 프로세스는 정확히 한 그룹에 들어간다."""
    groups = {}
    for p in procs:
        g = classify(view, p, ctx)
        if pred and not pred(p, g):
            continue
        d = groups.setdefault(g, dict(name=g, procs=[], cpu=0.0, rss=0, n=0))
        d["procs"].append(p)
        d["cpu"] += p["cpu"]
        d["rss"] += p["rss"]
        d["n"] += 1
    for d in groups.values():
        d["procs"].sort(key=lambda p: (-p["cpu"], -p["rss"], p["pid"]))
    return sorted(groups.values(), key=SORTS.get(sort, SORTS["cpu"]))
