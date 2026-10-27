#!/usr/bin/env python3
"""notif — 알림 기록 조회·통계·복사와 시스템 장애(실패한 서비스) 감시.

  notif list [-n 개수] [--app 앱] [--since 2h|3d|1w] [--grep 글자] [--urgent] [--problems]   최신이 1번
  notif apps [--since 7d]            앱별 묶음(건수, 긴급 건수, 마지막 알림)
  notif stats [--since 7d]           앱별·시간대별·일별 건수와 긴급도 분포
  notif problems                     시스템 문제: 지금 실패한 서비스 + 최근 문제 알림
  notif copy N [--body] [list 와 같은 조건]   list 의 N번 알림을 클립보드로(기본: 제목+본문, --body: 본문만)
  notif record                       (서비스용) 알림을 받아 기록한다
  notif health                       실패한 서비스를 확인해 새 실패를 알리고 waybar 를 갱신한다
  notif devices                      (서비스용) 장치 연결/해제·마운트·전원 어댑터 변화를 알림으로 알린다(devwatch.py)
  notif waybar                       waybar 모듈용 JSON(문제가 없으면 빈 출력 = 모듈이 사라짐)
  notif ui [all|apps|problems|stats] 대화형 화면(Notification Center)

기록: $NOTIF_LOG_DIR(기본 /var/log/custom-notify-logger)/<사용자>.log (logrotate 로 30일). 한 줄에 JSON 하나이고,
이전 형식(`[시각] [앱] [제목] 본문`)도 읽는다. "문제 알림" = 앱 이름이 system-health 이거나 긴급도(urgency)가 critical(2)인 것.
"""
import argparse
import collections
import datetime
import glob
import gzip
import json
import os
import re
import shutil
import subprocess
import sys

LOG_DIR = os.environ.get("NOTIF_LOG_DIR", "/var/log/custom-notify-logger")
USER = os.environ.get("USER", "unknown")
HEALTH_APP = "system-health"
WAYBAR_SIGNAL = "-RTMIN+9"
LEGACY = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] \[(.*?)\] \[(.*?)\] ?(.*)$")
TS_FMT = "%Y-%m-%d %H:%M:%S"
UNITS = {"m": 60, "h": 3600, "d": 86400, "w": 7 * 86400}


# ───────────────────────── 기록 읽기 ─────────────────────────
def parse_line(line: str):
    """한 줄 → {"ts": datetime, "app", "summary", "body", "urgency"(None=알 수 없음)}; 못 읽으면 None."""
    line = line.rstrip("\n")
    if not line:
        return None
    if line.startswith("{"):
        try:
            d = json.loads(line)
            return {"ts": datetime.datetime.strptime(d["ts"], TS_FMT), "app": d.get("app", ""), "summary": d.get("summary", ""),
                    "body": d.get("body", ""), "urgency": d.get("urgency")}
        except (ValueError, KeyError):
            return None
    m = LEGACY.match(line)
    if not m:
        return None
    return {"ts": datetime.datetime.strptime(m[1], TS_FMT), "app": m[2], "summary": m[3], "body": m[4], "urgency": None}


def log_files(log_dir: str = LOG_DIR, user: str = USER) -> list:
    """오래된 파일부터: .log.N(N 이 클수록 오래됨) → … → .log.1 → .log(현재)."""
    def age(path: str) -> int:
        m = re.search(r"\.log\.(\d+)", path)
        return -int(m[1]) if m else 1
    return sorted(glob.glob(f"{log_dir}/{user}.log*"), key=age)


def read_entries(log_dir: str = LOG_DIR, user: str = USER) -> list:
    """모든 기록(오래된 것부터). .gz 도 읽는다.
    **기록된 순서**를 유지한다: 부팅 직후 약 30초는 시스템 시각이 9시간 앞서(RTC 문제, posture.md 참고) 그 시각으로 정렬하면 "미래" 알림이 최신으로 올라온다."""
    out = []
    for path in log_files(log_dir, user):
        opener = gzip.open if path.endswith(".gz") else open
        try:
            with opener(path, "rt", encoding="utf-8", errors="replace") as f:
                out.extend(e for e in map(parse_line, f) if e)
        except OSError:
            continue
    return out


def parse_since(text: str, now: datetime.datetime):
    m = re.fullmatch(r"(\d+)([mhdw])", text or "")
    if not m:
        raise ValueError(f"기간은 30m / 2h / 3d / 1w 처럼 적어 주세요: {text!r}")
    return now - datetime.timedelta(seconds=int(m[1]) * UNITS[m[2]])


def is_problem(e: dict) -> bool:
    return e["app"] == HEALTH_APP or e["urgency"] == 2


def select(entries: list, app=None, since=None, grep=None, urgent=False, problems=False, app_like=None, words=()) -> list:
    """최신(가장 나중에 기록된 것)이 앞(1번)이 되도록 걸러서 돌려준다.
    app: 앱 이름 정확히 / app_like: 앱 이름에 글자가 들어 있음 / grep: 앱·제목·본문에 글자 / words: 그 글자들이 모두 들어 있음(검색창용)"""
    out = []
    words = [w.lower() for w in words]
    for e in reversed(entries):
        if app and e["app"] != app:
            continue
        if app_like and app_like.lower() not in e["app"].lower():
            continue
        if since and e["ts"] < since:
            continue
        hay = f"{e['app']} {e['summary']} {e['body']}".lower()
        if grep and grep.lower() not in hay:
            continue
        if words and not all(w in hay for w in words):
            continue
        if urgent and e["urgency"] != 2:
            continue
        if problems and not is_problem(e):
            continue
        out.append(e)
    return out


def parse_query(text: str, now: datetime.datetime) -> dict:
    """검색창 글자 → select 인자. `app:이름`(앱 이름에 포함) `is:problem` `is:urgent` `since:3h` 와 나머지 글자(모두 포함).
    clipui 의 검색창과 같은 방식. 잘못된 기간 등은 일반 글자로 취급한다."""
    q = {"app_like": None, "problems": False, "urgent": False, "since": None, "words": []}
    for tok in text.split():
        low = tok.lower()
        if low.startswith("app:") and len(tok) > 4:
            q["app_like"] = tok[4:]
        elif low == "is:problem":
            q["problems"] = True
        elif low == "is:urgent":
            q["urgent"] = True
        elif low.startswith("since:"):
            try:
                q["since"] = parse_since(low[6:], now)
            except ValueError:
                q["words"].append(tok)
        else:
            q["words"].append(tok)
    return q


def group_by_app(entries: list) -> list:
    """[(앱, 건수, 긴급 건수, 마지막 알림)] 건수 많은 순."""
    g = collections.OrderedDict()
    for e in entries:
        c = g.setdefault(e["app"], {"n": 0, "urgent": 0, "last": e["ts"]})
        c["n"] += 1
        c["urgent"] += e["urgency"] == 2
        c["last"] = max(c["last"], e["ts"])
    return sorted(((a, c["n"], c["urgent"], c["last"]) for a, c in g.items()), key=lambda r: (-r[1], r[0]))


def stats(entries: list) -> dict:
    by_hour = collections.Counter(e["ts"].hour for e in entries)
    by_day = collections.Counter(e["ts"].date().isoformat() for e in entries)
    urg = collections.Counter({0: 0, 1: 0, 2: 0, None: 0})
    for e in entries:
        urg[e["urgency"]] += 1
    return {"total": len(entries), "apps": group_by_app(entries), "by_hour": by_hour, "by_day": by_day, "urgency": urg}


# ───────────────────────── 표시 ─────────────────────────
def one_line(e: dict, width: int = 0) -> str:
    body = e["body"].replace("\n", " ⏎ ")
    s = f"{e['ts']:%m-%d %H:%M}  [{e['app']}] {e['summary']}" + (f" — {body}" if body else "")
    mark = "‼ " if is_problem(e) else ""
    s = mark + s
    return s if not width or len(s) <= width else s[: width - 1] + "…"


def cells(s):
    """표시 칸 수(한글·전각 2칸, 결합문자 0칸)."""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 0 if unicodedata.combining(c) else 1 for c in str(s))


def fit(s, n):
    """칸 폭 기준으로 n 칸에 맞춘다(길면 …로 자르고 짧으면 공백으로 채움) — f-string 의 :<n 은 글자 수라 한글 앱 이름 표가 어긋난다."""
    s = str(s)
    if cells(s) > n:
        while s and cells(s) > n - 1:
            s = s[:-1]
        s += "…"
    return s + " " * (n - cells(s))


def bar(n: int, top: int, width: int = 24) -> str:
    return "█" * (max(1, round(n / top * width)) if n else 0)


def render_stats(st: dict) -> str:
    if not st["total"]:
        return "기록된 알림이 없습니다."
    L = [f"알림 {st['total']}건", ""]
    u = st["urgency"]
    L.append(f"긴급도: 낮음 {u[0]} / 보통 {u[1]} / 긴급 {u[2]} / 알 수 없음(이전 기록) {u[None]}")
    L += ["", "앱별"]
    top = st["apps"][0][1]
    L += [f"  {fit(a, 24)} {n:>5}  {bar(n, top)}" + (f"  (긴급 {k})" if k else "") for a, n, k, _ in st["apps"][:15]]
    L += ["", "시간대별"]
    ht = max(st["by_hour"].values())
    L += [f"  {h:02d}시 {st['by_hour'].get(h, 0):>5}  {bar(st['by_hour'].get(h, 0), ht)}" for h in range(24) if st["by_hour"].get(h)]
    L += ["", "날짜별(최근 14일)"]
    days = sorted(st["by_day"].items())[-14:]
    dt = max(n for _, n in days)
    L += [f"  {d} {n:>5}  {bar(n, dt)}" for d, n in days]
    return "\n".join(L)


# ───────────────────────── 시스템 장애 감시 ─────────────────────────
def run(*cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def failed_units() -> list:
    """[(범위, 유닛)] — 시스템과 사용자 systemd 의 실패한 유닛."""
    out = []
    for scope, extra in (("system", []), ("user", ["--user"])):
        r = run("systemctl", *extra, "--failed", "--no-legend", "--plain", "--no-pager")
        for line in r.stdout.splitlines():
            parts = line.split()
            if parts and parts[0] == "●":      # 일부 버전은 앞에 점을 붙인다
                parts = parts[1:]
            if parts:
                out.append((scope, parts[0]))
    return out


def state_path() -> str:
    d = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "notif")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "health.json")


def load_state(path: str) -> dict:
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"failed": []}


def unit_log(scope: str, unit: str) -> str:
    extra = ["--user"] if scope == "user" else []
    r = run("journalctl", *extra, "-u", unit, "-n", "6", "--no-pager", "-o", "cat")
    return r.stdout.strip()[-600:]


def send_alert(scope: str, unit: str) -> None:
    body = unit_log(scope, unit) or "(로그를 읽지 못했습니다)"
    if shutil.which("notify-send"):
        run("notify-send", "-a", HEALTH_APP, "-u", "critical", "-i", "dialog-error", f"서비스 실패: {unit} ({scope})", body)


def refresh_waybar() -> None:
    run("pkill", WAYBAR_SIGNAL, "-x", "(.waybar-wrapped|waybar)")


def health(state_file=None, alert=send_alert, refresh=refresh_waybar, units=failed_units) -> dict:
    """실패한 서비스를 확인해 **새로 실패한 것만** 알리고, 상태 파일(waybar 용)을 갱신한다."""
    state_file = state_file or state_path()
    prev = {tuple(x) for x in load_state(state_file)["failed"]}
    cur = units()
    for scope, unit in cur:
        if (scope, unit) not in prev:
            alert(scope, unit)
    with open(state_file, "w") as f:
        json.dump({"failed": [list(x) for x in cur]}, f)
    if set(cur) != prev:
        refresh()
    return {"failed": cur, "new": [u for u in cur if u not in prev]}


def waybar_json(state_file=None) -> str:
    failed = load_state(state_file or state_path())["failed"]
    if not failed:
        return ""
    tip = "\n".join(f"{u} ({s})" for s, u in failed)
    return json.dumps({"text": f"⚠ {len(failed)}", "tooltip": f"실패한 서비스 {len(failed)}개\n{tip}\n\n클릭: 문제 화면", "class": "problem"}, ensure_ascii=False)


# ───────────────────────── 기록(서비스) ─────────────────────────
def hint_urgency(hints: dict):
    u = hints.get("urgency")
    return u.get("data") if isinstance(u, dict) else None


def entry_from_notify(data: list):
    """Notify(app, replaces_id, icon, summary, body, actions, hints, timeout) → 기록 한 줄(JSON) 또는 None."""
    if len(data) < 7 or not data[3]:
        return None
    return json.dumps({"ts": datetime.datetime.now().strftime(TS_FMT), "app": data[0], "summary": data[3], "body": data[4],
                       "urgency": hint_urgency(data[6] if isinstance(data[6], dict) else {})}, ensure_ascii=False)


def record(log_dir: str = LOG_DIR, user: str = USER) -> int:
    path = os.path.join(log_dir, f"{user}.log")
    match = "type='method_call',interface='org.freedesktop.Notifications',member='Notify'"
    p = subprocess.Popen(["busctl", "--user", "--json=short", "monitor", "--match", match], stdout=subprocess.PIPE, text=True, bufsize=1)
    for raw in p.stdout:
        try:
            msg = json.loads(raw)
        except ValueError:
            continue
        if msg.get("member") != "Notify":
            continue
        line = entry_from_notify(msg.get("payload", {}).get("data", []))
        if line:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
    return p.wait()


# ───────────────────────── 명령줄 ─────────────────────────
def copy_text(text: str) -> bool:
    """wl-copy 는 클립보드 내용을 계속 제공하려고 백그라운드로 남는다. 그 프로세스가 우리 터미널(pty)을 붙잡고 있으면
    복사하고 종료해도 kitty 창이 빈 화면으로 남으므로, 출력은 /dev/null 로 돌려 터미널과 분리한다."""
    if not shutil.which("wl-copy"):
        return False
    return subprocess.run(["wl-copy"], input=text, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def entry_text(e: dict, body_only: bool = False) -> str:
    return e["body"] if body_only else (e["summary"] + ("\n" + e["body"] if e["body"] else ""))


def cmd_problems(entries: list, now) -> int:
    cur = failed_units()
    print(f"지금 실패한 서비스: {len(cur)}개" if cur else "지금 실패한 서비스: 없음")
    for scope, unit in cur:
        print(f"  ✗ {unit} ({scope})   → systemctl{' --user' if scope == 'user' else ''} status {unit}")
    recent = select(entries, since=now - datetime.timedelta(days=7), problems=True)
    print(f"\n최근 7일 문제 알림: {len(recent)}건")
    for i, e in enumerate(recent[:30], 1):
        print(f"{i:3d}  {one_line(e, shutil.get_terminal_size().columns - 6)}")
    return 1 if cur else 0


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(prog="notif", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    def filters(p):
        p.add_argument("--app")
        p.add_argument("--since")
        p.add_argument("--grep")
        p.add_argument("--urgent", action="store_true")
        p.add_argument("--problems", action="store_true")

    p = sub.add_parser("list")
    p.add_argument("-n", type=int, default=30)
    filters(p)
    for name in ("apps", "stats"):
        sub.add_parser(name).add_argument("--since", default="30d")
    sub.add_parser("problems")
    p = sub.add_parser("copy")      # 번호는 같은 조건의 `notif list` 와 같다
    p.add_argument("n", type=int)
    p.add_argument("--body", action="store_true")
    filters(p)
    for name in ("record", "health", "waybar", "devices"):
        sub.add_parser(name)
    sub.add_parser("ui").add_argument("tab", nargs="?", default="all", choices=["all", "apps", "problems", "stats"])
    a = ap.parse_args(argv)
    now = datetime.datetime.now()

    if a.cmd == "record":
        return record()
    if a.cmd == "devices":
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import devwatch
        return devwatch.run()
    if a.cmd == "health":
        r = health()
        print(f"실패한 서비스 {len(r['failed'])}개, 새로 알린 것 {len(r['new'])}개")
        return 0
    if a.cmd == "waybar":
        out = waybar_json()
        if out:
            print(out)
        return 0
    if a.cmd == "ui":
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import notif_ui
        return notif_ui.run(a.tab)
    if not a.cmd:
        ap.print_help()
        return 2

    entries = read_entries()
    width = shutil.get_terminal_size().columns - 6
    try:
        since = parse_since(getattr(a, "since", None), now) if getattr(a, "since", None) else None
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    if a.cmd == "list":
        sel = select(entries, a.app, since, a.grep, a.urgent, a.problems)
        for i, e in enumerate(sel[: a.n], 1):
            print(f"{i:3d}  {one_line(e, width)}")
        if not sel:
            print("조건에 맞는 알림이 없습니다.")
        elif len(sel) > a.n:
            print(f"   … 그 외 {len(sel) - a.n}건 (-n 으로 더 보기)")
        return 0
    if a.cmd == "apps":
        for app, n, k, last in group_by_app(select(entries, since=since)):
            print(f"{fit(app, 28)} {n:>5}건" + (f"  긴급 {k}" if k else "") + f"   마지막 {last:%m-%d %H:%M}")
        return 0
    if a.cmd == "stats":
        print(render_stats(stats(select(entries, since=since))))
        return 0
    if a.cmd == "problems":
        return cmd_problems(entries, now)
    if a.cmd == "copy":
        sel = select(entries, a.app, since, a.grep, a.urgent, a.problems)
        if not 1 <= a.n <= len(sel):
            print(f"{a.n}번 알림이 없습니다(조건에 맞는 알림 {len(sel)}건). 같은 조건의 `notif list` 번호를 쓰세요.", file=sys.stderr)
            return 1
        ok = copy_text(entry_text(sel[a.n - 1], a.body))
        print("클립보드에 복사했습니다." if ok else "wl-copy 가 없어 복사하지 못했습니다.")
        return 0 if ok else 1
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
