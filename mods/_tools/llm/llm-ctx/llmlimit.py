"""llmlimit — llmui 10 「한도」 탭의 순수 로직(보정값 조회·고정). 화면과 무관해 단위 시험이 쉽다. 표준 라이브러리만 쓴다.

정본은 `donghans-limit-watch` 스킬의 `limitwatch.py`(llm-trust 05 계획 §3-6, D-5) — 보정 파일(`limit-calibration.json`)의 형식·고정 규칙·유효값 계산을
여기서 다시 구현하지 않고 그 모듈을 불러 쓰며, **쓰기는 항상 그 CLI(`pin`·`calibrate --write`)를 부른다**(규칙이 한 곳에 있도록).
스킬을 찾지 못하면 화면은 안내만 하고 아무것도 쓰지 않는다.
"""
from __future__ import annotations

import importlib.util
import math
import os
import subprocess
import sys

KEYS = (("five", "5h"), ("seven", "7d"))
MAX_PIN = 1000.0          # 고정값 상한(달러/포인트) — 오타 방지용 값. 실측은 5h 약 1.7·7d 약 10
_CLI_TIMEOUT = 60


def data_dir() -> str:
    """limits.jsonl 과 limit-calibration.json 이 있는 폴더. 시험은 LLMUI_LIMIT_DIR 로 바꾼다."""
    return os.environ.get("LLMUI_LIMIT_DIR") or os.path.expanduser("~/.local/share/claude-otel")


def limits_file() -> str:
    return os.path.join(data_dir(), "limits.jsonl")


def calib_file() -> str:
    return os.path.join(data_dir(), "limit-calibration.json")


def find_limitwatch() -> str | None:
    """limitwatch.py 경로: LLMUI_LIMITWATCH → 설치된 스킬(~/.claude/skills) → 소스 트리."""
    here = os.path.dirname(os.path.abspath(__file__))
    cands = [os.environ.get("LLMUI_LIMITWATCH"),
             os.path.expanduser("~/.claude/skills/donghans-limit-watch/scripts/limitwatch.py"),
             os.path.normpath(os.path.join(here, "..", "..", "..", "_data", "claude-skills", "donghans-limit-watch", "scripts", "limitwatch.py"))]
    return next((c for c in cands if c and os.path.isfile(c)), None)


def _load_module(path: str):
    spec = importlib.util.spec_from_file_location("limitwatch_for_llmui", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_view() -> dict:
    """보정 파일을 읽어 화면용으로: {"err": 문구|None, "updated": str, "rows": [행], "path": 파일}.
    행: plan·key(five|seven)·label·auto(자동 값 dict|None)·eff(중앙, p25, p75, n, 고정여부)|None·pinned(고정값|None)·suggest(제안 dict|None)·updated."""
    script = find_limitwatch()
    out = {"err": None, "updated": "", "rows": [], "path": calib_file(), "script": script}
    if not script:
        out["err"] = "limitwatch.py 를 찾지 못함(스킬 donghans-limit-watch 미배포) — 값을 읽지도 쓰지도 않는다"
        return out
    try:
        lw = _load_module(script)
    except Exception as e:      # 스킬 코드가 깨졌어도 화면은 산다
        out["err"] = f"limitwatch.py 를 불러오지 못함: {type(e).__name__}: {e}"
        return out
    d = lw.load_calib(calib_file())
    if d is None:
        out["err"] = f"보정 파일이 없거나 읽을 수 없음: {calib_file()} — 「자동 값 다시 계산」으로 만들 수 있다(조건을 못 채우면 만들어지지 않는다)"
        return out
    out["updated"] = d.get("updated", "")
    for plan, ent in sorted(d["plans"].items()):
        ent = ent if isinstance(ent, dict) else {}
        pin = ent.get("pinned") or {}
        sug = ent.get("suggest") or {}
        for key, label in KEYS:
            auto, eff = ent.get(key), lw.effective(ent, key)
            if not auto and not eff:
                continue
            out["rows"].append(dict(plan=plan, key=key, label=label, auto=auto, eff=eff, pinned=pin.get(key), suggest=sug.get(key), updated=ent.get("updated", "")))
    return out


def parse_pin(text: str) -> tuple[float | None, str]:
    """입력 글 → (값, 오류). 0 보다 크고 MAX_PIN 이하인 유한한 수만."""
    try:
        v = float(str(text).strip())
    except ValueError:
        return None, "숫자가 아님 — 1 포인트당 달러 값(예: 1.7)"
    if not math.isfinite(v) or v <= 0:
        return None, "0 보다 큰 수여야 한다"
    if v > MAX_PIN:
        return None, f"{MAX_PIN:g} 이하여야 한다(1 포인트당 달러 값 — 실측은 5h 약 1.7·7d 약 10)"
    return v, ""


def _run(args: list[str]) -> tuple[int, str]:
    script = find_limitwatch()
    if not script:
        return 1, "limitwatch.py 를 찾지 못함"
    try:
        r = subprocess.run([sys.executable, "-I", script, "--file", limits_file(), *args], capture_output=True, text=True, timeout=_CLI_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, f"실행 실패: {e}"
    return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()


def pin(plan: str, key: str, value: float, view: dict | None = None) -> tuple[bool, str]:
    """한 플랜의 5h 또는 7d 값을 고정한다. CLI 의 pin 은 주어진 키만 남기고 나머지 고정을 지우므로, 이미 고정된 다른 키는 함께 넘겨 보존한다."""
    if key not in dict(KEYS):
        return False, "5h·7d 만 고정할 수 있다"
    view = view or load_view()
    keep = {r["key"]: r["pinned"] for r in view["rows"] if r["plan"] == plan and r["pinned"]}
    keep[key] = value
    args = ["pin", "--plan", plan]
    for k, v in keep.items():
        args += [f"--{k}", repr(float(v))]
    rc, out = _run(args)
    return rc == 0, out


def unpin(plan: str) -> tuple[bool, str]:
    """그 플랜의 고정값을 모두 푼다(CLI 의 --unpin 은 5h·7d 를 함께 해제)."""
    rc, out = _run(["pin", "--plan", plan, "--unpin"])
    return rc == 0, out


def recalc() -> tuple[bool, str]:
    """자동 값 다시 계산(`calibrate --write`). 고정값이 있으면 자동 값은 제안 칸에만 쓰이고, 창 수·폭 기준을 못 채우면 파일이 그대로다."""
    rc, out = _run(["calibrate", "--write"])
    return rc == 0, out


def _f(v, nd=2) -> str:
    return "-" if v is None else f"{v:.{nd}f}"


def row_cells(r: dict) -> tuple:
    """표의 한 줄: 플랜·구분·실제 사용값·고정·자동 중앙·25~75분위·창 수·제안."""
    eff, auto = r["eff"], r["auto"]
    use = _f(eff[0]) if eff else "-"
    pin_s = _f(r["pinned"]) if r["pinned"] else "-"
    auto_s = _f(auto["median"]) if auto else "-"
    rng = f"{_f(auto['p25'])}~{_f(auto['p75'])}" if auto else "-"
    n = str(auto["n"]) if auto else "-"
    sug = r["suggest"]
    sug_s = f"{_f(sug['median'])}(창 {sug['n']})" if sug and sug.get("median") else "-"
    return (r["plan"], r["label"], use, pin_s, auto_s, rng, n, sug_s)


LIMIT_ACTIONS = ("limit_pin", "limit_unpin", "limit_recalc")      # 제한 모드(LLM 세션)에서 막을 쓰기 동작 — 조회는 허용

RESTRICTED_NOTICE = "제한 모드(LLM 세션 안에서 실행됨): 한도 탭은 읽기만 한다 — 값 고정·해제·다시 계산은 사람이 터미널에서 직접 llmui 를 실행했을 때만 쓸 수 있다."
