"""단일 알파벳 Binding 키 검사 — 한영 전환(fcitx)에 영향받는 키를 앱이 다시 쓰지 않게 한다.

`Binding("a,b", ...)` / `Binding("키", ...)` 의 첫 인자를 ',' 로 쪼개 `^[A-Za-z]$` 이면 위반.
사용: python3 lint_keys.py [소스.py ...]  (인자 없으면 uikit 앱 7개 전부). 종료 코드 = 위반 있으면 1.
`PENDING` 은 아직 변환하지 않은 앱의 남은 키 허용 목록 — 앱을 변환하면 그 앱을 지운다(최종 목표: 비어 있음).
"""
import ast, os, re, sys

TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
APPS = {
    "ctxui": "llm/llm-ctx/ctxui.py", "usageui": "observe/observe/usageui.py",
    "procui": "observe/process-manager/procui.py", "displayui": "desktop/monitor-manager/displayui.py",
    "llm-sessions": "llm/llm-sessions/llm_sessions.py", "notif": "desktop/notification-center/notif_ui.py",
    "clipui": "desktop/clipboard/clipui.py",
}
PENDING = set(APPS) - {"ctxui"}  # 변환 끝난 앱은 여기서 뺀다


def violations(path):
    src = open(path, encoding="utf-8").read()
    out = []
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "Binding" and n.args:
            a = n.args[0]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                for k in a.value.split(","):
                    if re.fullmatch(r"[A-Za-z]", k.strip()):
                        out.append((n.lineno, k.strip(), a.value))
    return out


def check_apps(only=None):
    """{앱: [(줄, 키, 원문)]} — PENDING 앱은 제외."""
    res = {}
    for name, rel in APPS.items():
        if name in PENDING or (only and name not in only):
            continue
        v = violations(os.path.join(TOOLS, rel))
        if v:
            res[name] = v
    return res


if __name__ == "__main__":
    files = sys.argv[1:]
    bad = 0
    for f in files or [os.path.join(TOOLS, r) for r in APPS.values()]:
        for ln, k, raw in violations(f):
            print(f"{f}:{ln}: 단일 알파벳 키 {k!r} ({raw!r})"); bad += 1
    sys.exit(1 if bad else 0)
