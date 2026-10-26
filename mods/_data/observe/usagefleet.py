"""usageui 「호스트」 탭의 데이터와 그리기 — 여러 호스트(공유 저장소 claude_ctx)의 전력 추이·앱 CPU 비교·확장 차이.
데이터는 `observectl fleet export`(JSON)를 별도 프로세스로 받는다(TUI 의 파이썬에는 psycopg 가 없다). 받기에 실패하면 마지막으로 받은 값(캐시)을 보여 주고 낡았음을 표시한다.
표시만 한다(읽기 전용). 순수 함수 위주라 시험이 쉽다."""
import json, os, shutil, subprocess, time
from rich.text import Text

import observe_core as core
import observe_fleet as fl
import usagechart as uc

COLORS = ["dark_orange", "cyan", "green", "magenta"]
DAYS = 3


def cache_path():
    return os.path.join(core.state_dir(), "fleet-view.json")


def load(days=DAYS, timeout=25):
    """(데이터, 안내) — 안내는 낡은 값이거나 못 받았을 때의 사유(None 이면 방금 받은 값). 데이터가 없으면 (None, 사유)."""
    exe = shutil.which("observectl")
    err = "observectl 이 없습니다"
    if exe:
        try:
            r = subprocess.run([exe, "fleet", "export", "--days", str(days)], capture_output=True, text=True, timeout=timeout)
            if r.returncode == 0 and r.stdout.strip():
                data = json.loads(r.stdout)
                try:
                    os.makedirs(os.path.dirname(cache_path()), exist_ok=True)
                    with open(cache_path(), "w") as f:
                        json.dump(data, f)
                except OSError:
                    pass
                return data, None
            err = ((r.stderr or r.stdout).strip().splitlines() or ["응답 없음"])[-1][:160]
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            err = str(e)[:160]
    try:
        with open(cache_path()) as f:
            data = json.load(f)
        return data, f"공유 저장소에서 못 받아 {time.strftime('%m-%d %H:%M', time.localtime(data.get('fetched', 0)))} 에 받은 값을 보임 — {err}"
    except (OSError, ValueError):
        return None, err


def others(data):
    me = data.get("me")
    return [h for h in data.get("hosts", []) if h != me]


def series(data, host):
    """(점 목록 [(t, v)], 단위, 지표 이름) — psys 가 있으면 psys, 없으면 패키지(CPU+GPU)."""
    rows = (data.get("power") or {}).get(host) or []
    if any(r[1] is not None for r in rows):
        return [(r[0], r[1]) for r in rows if r[1] is not None], "W", "psys"
    return [(r[0], r[2]) for r in rows if r[2] is not None], "W", "패키지"


def power_chart(data, host, w, h, idx=0):
    """호스트 하나의 시간별 평균 전력 그래프(Text, 통계 문자열). 시간 단위 점이라 틈 허용을 2.5시간으로 둔다."""
    pts, unit, kind = series(data, host)
    if not pts:
        return Text(f" {host}: 이 기간에 전력 값이 올라와 있지 않습니다(수집이 꺼져 있었을 수 있음)", style="grey50"), ""
    t1 = data.get("fetched", time.time()); t0 = t1 - data.get("days", DAYS) * 86400
    text, st = uc.chart(pts, t0, t1, w, h, unit, COLORS[idx % len(COLORS)], max_gap_s=2.5 * 3600)
    return text, f"{host} · {kind} · " + uc.stats_str(st, unit)


def compare_rows(data, base, other):
    """base 가 other 보다 높은 앱 표 행 [(앱, base%, other%, 표시)] — observe_fleet.compare_means 와 같은 기준."""
    m = data.get("means") or {}
    ma = {a: tuple(v) for a, v in (m.get(base) or {}).items()}
    mb = {a: tuple(v) for a, v in (m.get(other) or {}).items()}
    out = []
    for app, ac, bc, ax, bx, flag in fl.compare_means(ma, mb):
        out.append((app, f"{ac:.2f}", f"{bc:.2f}", "한쪽에만 있음" if flag == "a만" else f"{fl.RATIO:g}배↑"))
    return out


def inventory_rows(data):
    return [(h, b, e[:16] + "…", profs, f"v{ver}", "★ 서비스 워커" if sw else "") for h, b, e, profs, ver, sw in data.get("inventory_diff", [])]


def status_text(data, note, base, other):
    t = Text()
    if not data:
        t.append(f" 호스트 비교 데이터를 받지 못했습니다 — {note or ''}\n", style="yellow")
        t.append(" 각 호스트에서 `observectl fleet sync`(usageui 의 y 키)로 먼저 올려야 합니다. 서버(beelink-ser7-co)와 이 기기의 접속 허용도 확인하세요.", style="grey50")
        return t
    hosts, smp = data.get("hosts", []), data.get("samples", {})
    t.append(" 올라온 호스트: " + " · ".join(f"{h}(표본 {smp.get(h, 0):,}개)" for h in hosts) + "\n")
    t.append(f" 비교: {base} ↔ {other or '(다른 호스트 없음)'} · 최근 {data.get('days', DAYS)}일 · 기준 {base}\n")
    if note:
        t.append(f" ⚠ {note}\n", style="yellow")
    t.append(" 사용 패턴이 다른 호스트라 높다고 바로 문제는 아닙니다 — 의심 후보를 가리는 용도. o 키: 상대 호스트 바꾸기 · y: 이 호스트 동기화", style="grey50")
    return t
