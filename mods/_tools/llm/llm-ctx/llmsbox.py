"""llmsbox — llmui 대시보드의 「sbox 의존성 경고」 상자가 `sboxctl depwatch` 를 부르는 어댑터(plan sbox-depwatch 단계 4).
화면(Textual)을 모르고 표준 라이브러리만 쓴다. llmui 는 발견 사항 파일을 직접 읽지 않고 반드시 `sboxctl … --json`(ctl 공통 봉투)으로만 본다.

sboxctl 위치: 환경변수 `SBOXCTL` > `~/nixos/core/scripts/sboxctl`. 없으면 상자를 숨긴다(nix 가 PATH 에 설치하지 않으므로 `which` 로 찾지 않는다 —
sbox 호스트가 아닌 곳의 llmui 에서는 상자가 안 보이는 것이 정상). 읽기 전용: 이 모듈은 `list`·`report` 만 부른다(스캔·등급 변경은 사람이 sboxctl 로)."""
from __future__ import annotations

import json
import os
import subprocess

TIMEOUT = 15


def find_sboxctl() -> str | None:
    cand = os.environ.get("SBOXCTL") or os.path.expanduser("~/nixos/core/scripts/sboxctl")
    return cand if os.path.isfile(cand) else None


def _call(args: list[str]) -> dict:
    """sboxctl depwatch <args> --json 을 실행해 봉투(dict)를 돌려준다. 실패는 {"ok": False, "error": …}."""
    ctl = find_sboxctl()
    if not ctl:
        return {"ok": False, "error": "sboxctl 없음", "missing": True}
    try:
        p = subprocess.run(["bash", ctl, "depwatch", *args, "--json"], capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": f"sboxctl 실행 실패: {e}"}
    try:
        env = json.loads(p.stdout)
    except ValueError:
        return {"ok": False, "error": (p.stderr or p.stdout or f"종료 코드 {p.returncode}").strip()[:300]}
    return env if isinstance(env, dict) else {"ok": False, "error": "봉투 형식이 아님"}


def load() -> dict:
    """대시보드 상자용. 반환: {"available": bool, "error": str|None, "scanned_at": str|None, "rows": [{name, tier, total, warn, info, scanned_at}]}.
    available=False(sboxctl 없음)면 상자를 숨기고, error 가 있으면 한 줄로 알린다."""
    env = _call(["list"])
    if env.get("missing"):
        return {"available": False, "error": None, "scanned_at": None, "rows": []}
    if not env.get("ok"):
        return {"available": True, "error": env.get("error") or "알 수 없는 오류", "scanned_at": None, "rows": []}
    data = env.get("data") or {}
    rows = []
    for name, p in (data.get("projects") or {}).items():
        fs = p.get("findings") or []
        rows.append({"name": name, "tier": p.get("tier", "general"), "total": len(fs),
                     "warn": sum(1 for f in fs if f.get("severity") == "warn"), "info": sum(1 for f in fs if f.get("severity") != "warn"),
                     "scanned_at": p.get("scanned_at"),
                     "partial": bool(p.get("notes")),
                     "unchecked": not fs and any("검사 안 함" in n for n in (p.get("notes") or []))})   # 적용 감지기 없음 — 0건을 「안전」으로 읽지 않게 표시
    rows.sort(key=lambda r: (r["tier"] != "critical", -r["warn"], r["name"]))   # critical 먼저, 경고 많은 순
    return {"available": True, "error": None, "scanned_at": data.get("scanned_at"), "rows": rows}


def report(project: str) -> str:
    env = _call(["report", "--project", project])
    if env.get("ok"):
        return env.get("text") or "(내용 없음)"
    return f"보고서를 만들지 못했다: {env.get('error') or '알 수 없는 오류'}"
