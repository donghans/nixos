#!/usr/bin/env python3
"""Claude 구독 한도(5h/7d) 현재 상태와 감시 — limits.jsonl 기반.

사용:
  limitwatch.py status [--json] [--recent 30]   현재 상태 한 번(읽기 전용, 끝나면 종료)
  limitwatch.py watch [--spike 5 --window 10 --levels 50,70,80,90 --poll 5
                       --forecast 150,200 --forecast-min-elapsed 30 --forecast-min-used 10]
                                                  임계값에서만 한 줄 출력(Monitor 용). 시작 때 과거를 알림으로 재생하지 않는다.
                                                  --forecast: 창 평균 속도로 리셋까지 외삽한 예측 도달치(%)가 단계에 닿으면 알림. 빈 값이면 끔.
표준 라이브러리만 쓴다. 5h/7d 는 계정 전체 값이라 모든 세션의 기록을 본다.
"""
import argparse, datetime as dt, json, os, sys, time

FILE = os.path.expanduser('~/.local/share/claude-otel/limits.jsonl')
TAIL = 512 * 1024


def parse_ts(s):
    try:
        return dt.datetime.fromisoformat(s).timestamp()
    except (TypeError, ValueError):
        return None


def rec(line):
    """한 줄 → 쓸 수 있는 레코드(시각·5h 값 없으면 None)"""
    try:
        d = json.loads(line)
    except ValueError:
        return None
    t = parse_ts(d.get('ts'))
    f, s = d.get('five_hour') or {}, d.get('seven_day') or {}
    if t is None or f.get('used_percentage') is None:
        return None
    return dict(t=t, f=f['used_percentage'], fr=f.get('resets_at'), s=s.get('used_percentage'), sr=s.get('resets_at'),
                sid=str(d.get('session_id', ''))[:8], cost=d.get('cost_usd') or 0, acct=d.get('account_email'))


def tail_records(path):
    with open(path, 'rb') as fh:
        size = fh.seek(0, 2)
        fh.seek(max(0, size - TAIL))
        data = fh.read().decode(errors='ignore')
    lines = data.splitlines()[1:] if size > TAIL else data.splitlines()
    return [r for r in map(rec, lines) if r]


def hhmm(t):
    return dt.datetime.fromtimestamp(t).strftime('%H:%M') if t else '?'


def status(a):
    try:
        recs = tail_records(a.file)
    except OSError as e:
        print(f'못 쟀음: {a.file} 을 읽지 못함 ({e})'); return 1
    if not recs:
        print('못 쟀음: 기록에 5h 값이 있는 레코드가 없음'); return 1
    last = recs[-1]
    age = time.time() - last['t']
    win = [r for r in recs if r['fr'] == last['fr'] and r['t'] >= last['t'] - a.recent * 60]
    delta = last['f'] - min(r['f'] for r in win)
    per = {}
    for r in win:                       # cost_usd 는 세션 누적이라 구간 안 증가분이 그 세션의 몫
        lo, hi = per.get(r['sid'], (r['cost'], r['cost']))
        per[r['sid']] = (min(lo, r['cost']), max(hi, r['cost']))
    top = sorted(((hi - lo, s) for s, (lo, hi) in per.items() if hi > lo), reverse=True)[:3]
    out = dict(five_hour=last['f'], five_hour_resets=last['fr'], seven_day=last['s'], seven_day_resets=last['sr'],
               record_age_s=round(age), recent_min=a.recent, recent_delta=delta,
               recent_top_sessions=[dict(session=s, cost_usd=round(c, 2)) for c, s in top], account=last['acct'])
    if a.json:
        print(json.dumps(out, ensure_ascii=False)); return 0
    left = f"리셋 {hhmm(last['fr'])}" if last['fr'] else '리셋 시각 불명'
    s7 = f"{last['s']:.0f}%" if last['s'] is not None else '?'
    print(f"5h {last['f']:.0f}% ({left}) · 7d {s7} · 최근 {a.recent}분 5h {delta:+.0f}p · 마지막 기록 {age/60:.0f}분 전({hhmm(last['t'])})")
    if top:
        print('  최근 구간 비용 상위(세션 앞 8자): ' + ', '.join(f'{s} ${c:.2f}' for c, s in top))
    if age > 600:
        print('  ※ 기록은 어느 세션이든 상태 표시줄이 갱신될 때만 남는다. 10분 넘게 낡았으면 그 사이 사용분은 안 보인다.')
    return 0


FIVE_H = 5 * 3600
GRID = 300      # 소진 예측은 5분 격자로만 평가한다


def forecast(t, used, resets_at):
    """창 평균 속도로 리셋까지 외삽한 5h 도달 예측(%). 경과 시간 계산이 안 되면 None"""
    if not resets_at:
        return None
    el, left = t - (resets_at - FIVE_H), resets_at - t
    if el <= 0 or left <= 0:
        return None
    return used + used / el * left


def watch(a):
    levels = sorted(float(x) for x in a.levels.split(','))
    try:
        pos = os.path.getsize(a.file)   # 시작 때 파일 끝부터 — 과거는 알림으로 재생하지 않는다
        recs = tail_records(a.file)
    except OSError:
        pos, recs = 0, []
    fc_levels = sorted(float(x) for x in a.forecast.split(',') if x.strip())
    fc_fired, fc_streak, fc_last = set(), {}, 0
    hist, fired, cur, base7, sr7 = [], set(), None, None, None
    if recs:
        last = recs[-1]
        cur, hist = last['fr'], [(r['t'], r['f']) for r in recs if r['fr'] == last['fr'] and r['t'] >= last['t'] - a.window * 60]
        f0 = forecast(last['t'], last['f'], last['fr'])
        fc_fired = {lv for lv in fc_levels if f0 is not None and f0 >= lv}
        fc_last = last['t']
        fired = {lv for lv in levels if last['f'] >= lv}   # 이미 넘은 수준은 상태 줄에 있으니 다시 울리지 않는다
        base7, sr7 = last['s'], last['sr']
        s7 = f"{last['s']:.0f}%" if last['s'] is not None else '?'
        print(f"[watch] 시작 5h {last['f']:.0f}% (리셋 {hhmm(last['fr'])}) · 7d {s7} · 기록 {(time.time()-last['t'])/60:.0f}분 전 "
              f"— 이 값이 현재 기준. 알림 조건: {a.window:.0f}분 내 +{a.spike:g}p, 5h {','.join(f'{l:.0f}' for l in levels)}%"
              + (f", 소진 예측 {','.join(f'{l:.0f}' for l in fc_levels)}%" if fc_levels else ''), flush=True)
    else:
        print('[watch] 시작 — 5h 기록 없음(상태 표시줄이 기록하면 시작)', flush=True)
    while True:
        try:
            size = os.path.getsize(a.file)
        except OSError:
            size = 0
        if size < pos:
            pos = 0
        if size > pos:
            with open(a.file, errors='ignore') as fh:
                fh.seek(pos); chunk = fh.read(); pos = fh.tell()
            for r in filter(None, map(rec, chunk.splitlines())):
                if r['fr'] != cur:              # 5h 창이 바뀜 — 윈도·수준 초기화
                    cur, hist, fired = r['fr'], [], set()
                    fc_fired, fc_streak, fc_last = set(), {}, 0
                hist = [(t, v) for t, v in hist + [(r['t'], r['f'])] if r['t'] - t <= a.window * 60]
                lo = min(v for _, v in hist)
                if r['f'] - lo >= a.spike:
                    print(f"[watch] 5h 급증 {lo:.0f}%→{r['f']:.0f}% ({a.window:.0f}분 내, 기록 세션 {r['sid']}) — 하던 일을 멈추고 사용자에게 알리세요", flush=True)
                    hist = [(r['t'], r['f'])]
                for lv in levels:
                    if r['f'] >= lv and lv not in fired:
                        fired.add(lv)
                        act = '새 작업을 시작하지 말고 사용자에게 묻습니다' if lv >= 70 else '사용자에게 알리세요'
                        print(f"[watch] 5h {lv:.0f}% 도달(현재 {r['f']:.0f}%, 리셋 {hhmm(r['fr'])}) — {act}", flush=True)
                if fc_levels and r['fr'] and r['t'] - fc_last >= GRID:
                    fc_last = r['t']
                    el = r['t'] - (r['fr'] - FIVE_H)
                    fc = forecast(r['t'], r['f'], r['fr']) if el >= a.forecast_min_elapsed * 60 and r['f'] >= a.forecast_min_used else None
                    for lv in fc_levels:
                        fc_streak[lv] = fc_streak.get(lv, 0) + 1 if fc is not None and fc >= lv else 0
                        if fc_streak[lv] >= 2 and lv not in fc_fired:     # 연속 두 번 넘어야 확정(일시적 급증 제외)
                            fc_fired.add(lv)
                            left = (r['fr'] - r['t']) / 60
                            tleft = (100 - r['f']) / (r['f'] / el) / 60 if r['f'] else 0
                            print(f"[watch] 5h 소진 예측 {fc:.0f}% (기준 {lv:.0f}%) — 현재 {r['f']:.0f}%, 이 속도면 약 {tleft:.0f}분 뒤 소진, "
                                  f"리셋까지 {left:.0f}분 — 사용량을 줄일지 사용자에게 알리세요", flush=True)
                if r['s'] is not None:
                    if base7 is None or r['sr'] != sr7: base7, sr7 = r['s'], r['sr']   # 주간 창이 바뀌면 기준 재설정
                    if r['s'] - base7 >= 3:
                        print(f"[watch] 주간 {base7:.0f}%→{r['s']:.0f}%", flush=True); base7 = r['s']
        time.sleep(a.poll)


ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument('--file', default=FILE)
sub = ap.add_subparsers(dest='cmd', required=True)
p = sub.add_parser('status'); p.add_argument('--json', action='store_true'); p.add_argument('--recent', type=float, default=30)
p = sub.add_parser('watch')
p.add_argument('--spike', type=float, default=5); p.add_argument('--window', type=float, default=10)
p.add_argument('--levels', default='50,70,80,90'); p.add_argument('--poll', type=float, default=5)
p.add_argument('--forecast', default='150,200'); p.add_argument('--forecast-min-elapsed', type=float, default=30)
p.add_argument('--forecast-min-used', type=float, default=10)
a = ap.parse_args()
try:
    sys.exit({'status': status, 'watch': watch}[a.cmd](a))
except KeyboardInterrupt:
    pass
