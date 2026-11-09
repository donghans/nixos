#!/usr/bin/env python3
"""Claude 구독 한도(5h/7d) 현재 상태와 감시 — limits.jsonl 기반.

사용:
  limitwatch.py status [--json] [--recent 30]   현재 상태 한 번(읽기 전용, 끝나면 종료)
  limitwatch.py watch [--spike 5 --window 10 --levels 50,70,80,90 --poll 5
                       --forecast 150,200 --forecast-min-elapsed 30 --forecast-min-used 10]
                                                  임계값에서만 한 줄 출력(Monitor 용). 시작 때 과거를 알림으로 재생하지 않는다.
                                                  --forecast: 창 평균 속도로 리셋까지 외삽한 예측 도달치(%)가 단계에 닿으면 알림. 빈 값이면 끔.
묻는 선(새 큰 작업 전 확인)은 플랜별: max_5x·max_20x 는 5h 80%·7d 90%, 그 밖(pro·불명)은 70%. 상태 줄에 플랜과 판정이 나온다.
표준 라이브러리만 쓴다. 5h/7d 는 계정 전체 값이라 모든 세션의 기록을 본다.
"""
import argparse, datetime as dt, json, os, statistics, sys, time, tempfile

FILE = os.path.expanduser('~/.local/share/claude-otel/limits.jsonl')
TAIL = 512 * 1024

# 「새 큰 작업을 시작하기 전에 사용자에게 묻는」 사용률(%) — 플랜별. max 플랜은 5h 80%·7d 90% 까지 안전하다(사용자 지시 2026-10-28).
# pro·알 수 없는 플랜은 보수적으로 70%. 알림 수준(--levels)은 이것과 별개로 그대로 50/70/80/90 이다.
ASK = {'max_5x': (80, 90), 'max_20x': (80, 90)}
ASK_DEFAULT = (70, 70)


def plan():
    """현재 계정의 플랜(max_5x·max_20x·pro …). LIMITWATCH_PLAN 이 있으면 그 값. 상태 표시줄(claude-usage-statusline)과 같은 방식으로 ~/.claude.json 에서 읽는다."""
    if os.environ.get('LIMITWATCH_PLAN'):
        return os.environ['LIMITWATCH_PLAN']
    for p in (os.path.join(os.environ.get('CLAUDE_CONFIG_DIR', ''), '.claude.json'), os.path.expanduser('~/.claude.json')):
        try:
            a = json.load(open(p)).get('oauthAccount') or {}
            t = (a.get('userRateLimitTier') or a.get('seatTier') or '').replace('default_claude_', '').replace('default_', '')
            if t:
                return t
        except Exception:
            pass
    return None


def ask_levels():
    pl = plan()
    return pl, ASK.get(pl, ASK_DEFAULT)


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
                sid=str(d.get('session_id', ''))[:8], cost=d.get('cost_usd') or 0, acct=d.get('account_email'),
                plan=d.get('account_plan'), model=d.get('model') or '')


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
        msg = f'못 쟀음: {a.file} 을 읽지 못함 ({e})'
        print(json.dumps({'error': msg}, ensure_ascii=False) if a.json else msg); return 1
    if not recs:
        msg = '못 쟀음: 기록에 5h 값이 있는 레코드가 없음'
        print(json.dumps({'error': msg}, ensure_ascii=False) if a.json else msg); return 1
    last = recs[-1]
    age = time.time() - last['t']
    win = [r for r in recs if r['fr'] == last['fr'] and r['t'] >= last['t'] - a.recent * 60]
    delta = last['f'] - min(r['f'] for r in win)
    per = {}
    for r in win:                       # cost_usd 는 세션 누적이라 구간 안 증가분이 그 세션의 몫
        lo, hi = per.get(r['sid'], (r['cost'], r['cost']))
        per[r['sid']] = (min(lo, r['cost']), max(hi, r['cost']))
    top = sorted(((hi - lo, s) for s, (lo, hi) in per.items() if hi > lo), reverse=True)[:3]
    pl, (ask5, ask7) = ask_levels()
    over = [n for n, v, lim in (('5h', last['f'], ask5), ('7d', last['s'], ask7)) if v is not None and v >= lim]
    out = dict(plan=pl, ask_five_hour=ask5, ask_seven_day=ask7, ask_now=bool(over),
               five_hour=last['f'], five_hour_resets=last['fr'], seven_day=last['s'], seven_day_resets=last['sr'],
               record_age_s=round(age), recent_min=a.recent, recent_delta=delta,
               recent_top_sessions=[dict(session=s, cost_usd=round(c, 2)) for c, s in top], account=last['acct'])
    if a.json:
        print(json.dumps(out, ensure_ascii=False)); return 0
    left = f"리셋 {hhmm(last['fr'])}" if last['fr'] else '리셋 시각 불명'
    s7 = f"{last['s']:.0f}%" if last['s'] is not None else '?'
    print(f"5h {last['f']:.0f}% ({left}) · 7d {s7} · 최근 {a.recent}분 5h {delta:+.0f}p · 마지막 기록 {age/60:.0f}분 전({hhmm(last['t'])})")
    print(f"  플랜 {pl or '알 수 없음(보수적으로 70%)'} — 새 큰 작업 전 확인선 5h {ask5}%·7d {ask7}%: "
          + (f"{'·'.join(over)} 가 확인선 이상이다 — 새 큰 작업을 시작하지 말고 사용자에게 묻는다" if over else '둘 다 아래라 진행해도 된다(알림 수준 50/70/80/90 은 별개)'))
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
    pl, (ask5, ask7) = ask_levels()
    warned7 = None
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
              f"— 이 값이 현재 기준(플랜 {pl or '?'}: 묻는 선 5h {ask5}%·7d {ask7}%). 알림 조건: {a.window:.0f}분 내 +{a.spike:g}p, 5h {','.join(f'{l:.0f}' for l in levels)}%"
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
                        act = '새 작업을 시작하지 말고 사용자에게 묻습니다' if lv >= ask5 else '사용자에게 알리세요'
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
                    if r['s'] >= ask7 and warned7 != r['sr']:
                        warned7 = r['sr']
                        print(f"[watch] 주간 {r['s']:.0f}% 도달(플랜 {pl or '?'} 확인선 {ask7}%) — 새 작업을 시작하지 말고 사용자에게 묻습니다", flush=True)
                    if r['s'] - base7 >= 3:
                        print(f"[watch] 주간 {base7:.0f}%→{r['s']:.0f}%", flush=True); base7 = r['s']
        time.sleep(a.poll)




# ───────────────────────── 보정(calibrate) — 1 % 가 몇 달러인가 ─────────────────────────
CAL_START = dt.datetime.fromisoformat('2026-10-28T00:00:00+09:00').timestamp()   # 이 날 전 기록은 불완전해 $/pt 가 흩어진다(계획 §3-2)
CAL_DAYS = 21
MIN_WINDOWS_5H, MIN_WINDOWS_7D = 8, 2     # --write 가 값을 쓰는 최소 창 수(5h·7d). 7d 는 완주한 주가 적어 2
MAX_SPREAD = 0.5                          # 5h: (p75−p25)/중앙값, 7d: (최대−최소)/중앙값 이 이 값을 넘으면 쓰지 않는다
SEVEN_D = 7 * 86400
STALE_S = 600
OPUS_WARN = 0.15                          # 최근 6시간 비용 증가 중 opus 비중이 이 이상이면 경고(보정은 sonnet 위주에서만 검증됨)


def all_records(path):
    """파일 전체를 줄 단위로 읽어 레코드로(보정·사후 비교용)"""
    with open(path, errors='ignore') as fh:
        return [r for r in map(rec, fh) if r]


def calib_path(a):
    return os.path.join(os.path.dirname(os.path.abspath(a.file)), 'limit-calibration.json')


def estimates_path(a):
    return os.path.join(os.path.dirname(os.path.abspath(a.file)), 'limit-estimates.jsonl')


def cost_gain(rs):
    """레코드(시각순) 안에서 세션별 cost_usd 증가분 합. 비용이 줄어드는 줄은 건너뛴다(그 줄은 기준도 바꾸지 않는다)."""
    prev, tot = {}, 0.0
    for r in rs:
        p = prev.get(r['sid'])
        if p is None:
            prev[r['sid']] = r['cost']
        elif r['cost'] >= p:
            tot += r['cost'] - p
            prev[r['sid']] = r['cost']
    return tot


def window_points(recs, now, since, days):
    """플랜별 창 단위 $/pt 목록. 계정·플랜 필드가 있는 줄만, 계정·창(resets_at)별로 묶는다.
    5h: 창의 첫 5h% ≤ 3, 최고 % ≥ 10, 창 시작 ≥ since 이고 최근 days 일 안.  7d: 창의 첫 7d% ≤ 5, 증가 ≥ 15p, 시작 ≥ since, 최근 days 일 이전부터 시작해도 됨(주는 길다)."""
    out = {}
    g5, g7 = {}, {}
    for r in sorted(recs, key=lambda r: r['t']):
        if not r['acct'] or not r['plan']:
            continue
        if r['fr']:
            g5.setdefault((r['acct'], r['plan'], r['fr']), []).append(r)
        if r['sr'] and r['s'] is not None:
            g7.setdefault((r['acct'], r['plan'], r['sr']), []).append(r)
    for (acct, plan, fr), rs in g5.items():
        start = fr - FIVE_H
        if start < since or start < now - days * 86400:
            continue
        top = max(r['f'] for r in rs)
        if rs[0]['f'] > 3 or top < 10:
            continue
        usd = cost_gain(rs)
        if usd > 0:
            out.setdefault(plan, {'five': [], 'seven': []})['five'].append(dict(start=start, usd_per_pt=usd / top, usd=round(usd, 2), pt=top))
    for (acct, plan, sr), rs in g7.items():
        start = sr - SEVEN_D
        if start < since or rs[0]['s'] > 5:
            continue
        gain = max(r['s'] for r in rs) - rs[0]['s']
        if gain < 15:
            continue
        usd = cost_gain(rs)
        if usd > 0:
            out.setdefault(plan, {'five': [], 'seven': []})['seven'].append(dict(start=start, usd_per_pt=usd / gain, usd=round(usd, 2), pt=gain, ended=sr <= now))
    return out


def summarize_pts(pts):
    v = sorted(p['usd_per_pt'] for p in pts)
    if not v:
        return None
    q = statistics.quantiles(v, n=4, method='inclusive') if len(v) >= 2 else [v[0]] * 3
    return dict(median=round(statistics.median(v), 4), p25=round(q[0], 4), p75=round(q[2], 4), min=round(v[0], 4), max=round(v[-1], 4), n=len(v))


def load_calib(path):
    try:
        d = json.load(open(path))
        return d if isinstance(d, dict) and isinstance(d.get('plans'), dict) else None
    except (OSError, ValueError):
        return None


def effective(entry, key):
    """보정 항목의 실제로 쓰는 값(고정값이 있으면 그것). (중앙, p25, p75, n, 고정여부) 또는 None"""
    if not entry:
        return None
    auto = entry.get(key)
    pin = (entry.get('pinned') or {}).get(key)
    if pin:
        if auto and auto.get('median'):
            k = pin / auto['median']
            return pin, auto['p25'] * k, auto['p75'] * k, auto['n'], True
        return pin, pin, pin, 0, True
    if auto:
        return auto['median'], auto['p25'], auto['p75'], auto['n'], False
    return None


def write_json_atomic(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.cal-')
    with os.fdopen(fd, 'w') as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def calibrate(a):
    try:
        recs = all_records(a.file)
    except OSError as e:
        msg = f'못 쟀음: {a.file} 을 읽지 못함 ({e})'
        print(json.dumps({'error': msg}, ensure_ascii=False) if a.json else msg); return 1
    now = a.now if a.now is not None else time.time()
    since = parse_ts(a.since) if a.since else CAL_START
    pts = window_points(recs, now, since, a.days)
    calc, report, notes = {}, [], []
    for plan_, w in sorted(pts.items()):
        s5, s7 = summarize_pts(w['five']), summarize_pts(w['seven'])
        calc[plan_] = dict(five=s5, seven=s7)
        report.append(dict(plan=plan_, five=s5, seven=s7))
    old = load_calib(calib_path(a))
    wrote = False
    if a.write:
        new = dict(version=1, source=os.path.basename(a.file), updated=dt.datetime.fromtimestamp(now).astimezone().isoformat(timespec='seconds'),
                   plans=json.loads(json.dumps((old or {}).get('plans', {}))))
        for plan_, c in calc.items():
            ent = new['plans'].setdefault(plan_, {})
            ok5 = c['five'] and c['five']['n'] >= MIN_WINDOWS_5H and (c['five']['p75'] - c['five']['p25']) <= MAX_SPREAD * c['five']['median']
            if not ok5:
                n5 = c['five']['n'] if c['five'] else 0
                notes.append(f"{plan_}: 5h 값을 쓰지 않음 — 창 {n5}개(최소 {MIN_WINDOWS_5H})"
                             + (f", 25/75분위 폭 {(c['five']['p75']-c['five']['p25'])/c['five']['median']:.0%}(최대 {MAX_SPREAD:.0%})" if c['five'] and n5 >= MIN_WINDOWS_5H else '') + ' — 기존 파일 유지')
                continue
            ok7 = c['seven'] and c['seven']['n'] >= MIN_WINDOWS_7D and (c['seven']['max'] - c['seven']['min']) <= MAX_SPREAD * c['seven']['median']
            if not ok7:
                notes.append(f"{plan_}: 7d 값은 쓰지 않음(완주·증가 큰 주 {c['seven']['n'] if c['seven'] else 0}개, 최소 {MIN_WINDOWS_7D}·최대−최소 폭 ≤ {MAX_SPREAD:.0%}) — 7d 는 기존 값 유지")
            pinned = ent.get('pinned') or {}
            fresh = dict(five=c['five'], seven=c['seven'] if ok7 else ent.get('seven'))
            if pinned.get('five') or pinned.get('seven'):    # 수동으로 고정한 값은 자동이 덮어쓰지 않는다 — 제안 칸에만(D-6)
                ent['suggest'] = dict(five=c['five'], seven=c['seven'] if ok7 else None, at=new['updated'])
                notes.append(f"{plan_}: 고정값이 있어 자동 값은 suggest 칸에만 씀")
            else:
                ent.update(fresh); ent.pop('suggest', None)
            ent['updated'] = new['updated']
            ent.setdefault('pinned', {})
            wrote = True
        if wrote:
            write_json_atomic(calib_path(a), new)
    if a.json:
        print(json.dumps(dict(plans=report, wrote=wrote, notes=notes, path=calib_path(a)), ensure_ascii=False)); return 0
    if not (a.quiet and not a.write):
        if not report:
            print('보정할 창이 없음(계정·플랜이 적힌 기록·조건에 맞는 창 없음)')
        for r in report:
            for k, lab in (('five', '5h'), ('seven', '7d')):
                s = r[k]
                print(f"{r['plan']} {lab}: " + (f"$/pt 중앙 {s['median']:.2f} (25/75분위 {s['p25']:.2f}~{s['p75']:.2f}, 범위 {s['min']:.2f}~{s['max']:.2f}, 창 {s['n']}개)" if s else '해당 창 없음'))
        print('보정 파일 ' + (f'갱신: {calib_path(a)}' if wrote else ('갱신 안 함' if a.write else '쓰지 않음(--write 로 저장)')))
    for n_ in notes:
        print('  ' + n_)
    return 0


def pin(a):
    """보정값을 손으로 고정(자동 갱신은 suggest 칸에만 씀). --unpin 으로 해제."""
    path = calib_path(a)
    d = load_calib(path) or dict(version=1, plans={})
    ent = d['plans'].setdefault(a.plan, {})
    if a.unpin:
        ent['pinned'] = {}
    else:
        if a.five is None and a.seven is None:
            print('--five·--seven 중 하나가 필요(또는 --unpin)'); return 1
        if any(x is not None and x <= 0 for x in (a.five, a.seven)):
            print('고정값은 0 보다 커야 함'); return 1
        ent['pinned'] = {k: v for k, v in (('five', a.five), ('seven', a.seven)) if v is not None}
    write_json_atomic(path, d)
    print(f"{a.plan} 고정: {ent['pinned'] or '해제'}")
    return 0


# ───────────────────────── 예상(estimate) — 작업이 끝났을 때 몇 % 인가 ─────────────────────────
VERDICT_ORDER = ['go', 'notify', 'ask', 'ask-now']
VERDICT_TEXT = {'go': '진행', 'notify': '한 줄 알리고 진행(예상 범위 상단이 확인선을 넘음)', 'ask': '묻기(예상 중앙값이 확인선을 넘음)',
                'ask-now': '묻기(이미 현재 값이 확인선 이상 — 질문에 이 예측을 곁들인다)'}


def judge(cur, mid, hi, ask):
    if cur is None:
        return None
    if cur >= ask:
        return 'ask-now'
    return 'ask' if mid >= ask else 'notify' if hi >= ask else 'go'


def opus_share(recs, now, hours=6):
    """최근 hours 시간 비용 증가 중 opus 비중(없으면 None). 증가분은 그 줄의 모델에 돌린다."""
    prev, tot, opus = {}, 0.0, 0.0
    for r in sorted((r for r in recs if r['t'] >= now - hours * 3600), key=lambda r: r['t']):
        p = prev.get(r['sid'])
        if p is not None and r['cost'] > p:
            tot += r['cost'] - p
            if 'opus' in r['model']:
                opus += r['cost'] - p
        if p is None or r['cost'] >= p:
            prev[r['sid']] = r['cost']
    return opus / tot if tot > 0 else None


def fail(a, msg):
    msg = '못 쟀음: ' + msg
    print(json.dumps({'error': msg}, ensure_ascii=False) if a.json else msg + '\n  (전역 지침: 못 쟀음이면 확인선 70 % 로 간주하고 사용자에게 못 쟀다고 알린다)')
    return 1


def estimate(a):
    now = a.now if a.now is not None else time.time()
    given = [x for x in (a.usd, a.agents, a.minutes) if x is not None]
    if len(given) != 1:
        return fail(a, '작업 크기는 --usd · --agents(+--per-agent) · --minutes 중 정확히 하나로 준다')
    if a.agents is not None and a.per_agent is None:
        return fail(a, '에이전트 단가 없음 — 기본 단가를 두지 않는다. --per-agent USD 를 주거나 --usd 로 작업 전체 달러를 준다')
    if any(x is not None and x <= 0 for x in (a.usd, a.agents, a.minutes, a.per_agent)):
        return fail(a, '크기·단가는 0 보다 커야 함')
    pl = plan()
    cal = load_calib(calib_path(a))
    ent = (cal or {}).get('plans', {}).get(pl) if pl else None
    five = effective(ent, 'five')
    if not five:
        return fail(a, f"보정 없음(플랜 {pl or '알 수 없음'}) — 보정은 창이 충분한 플랜(현재 max_5x 만 계획)만 있다. "
                       f"`limitwatch.py calibrate --write` 를 먼저(창이 모자라면 쓰이지 않는다). 파일: {calib_path(a)}")
    seven = effective(ent, 'seven')
    try:
        recs = tail_records(a.file)
    except OSError as e:
        return fail(a, f'{a.file} 을 읽지 못함 ({e})')
    if not recs:
        return fail(a, '기록에 5h 값이 있는 레코드가 없음')
    last = recs[-1]
    age = now - last['t']
    if not last['fr'] or last['fr'] <= now:
        return fail(a, '마지막 기록의 5h 창이 이미 끝났음(새 창의 값이 아직 기록되지 않음) — 현재 %를 알 수 없다')
    u5, p25, p75 = five[0], five[1], five[2]
    # 현재 세션과 다른 세션 속도
    ex = (a.exclude_session or '')[:8]
    win = [r for r in recs if r['fr'] == last['fr'] and r['t'] >= last['t'] - a.interval * 60]
    span = (last['t'] - win[0]['t']) / 60
    delta = last['f'] - win[0]['f']
    own_usd = cost_gain([r for r in win if r['sid'] == ex]) if ex else 0.0
    notes = []
    if ex and not any(r['sid'] == ex for r in win):
        notes.append('현재 세션의 기록이 구간에 없음 — 다른 세션 속도에 이 세션이 섞였을 수 있다')
    elif not ex:
        notes.append('현재 세션 ID 를 몰라(--exclude-session 도 CLAUDE_CODE_SESSION_ID 도 없음) 다른 세션 속도에 이 세션이 섞인다')
    # 작업 크기 → 달러, 시간
    if a.minutes is not None:
        if own_usd <= 0 or span <= 0:
            return fail(a, '--minutes 는 현재 세션의 최근 비용 속도가 필요한데 구간 안에 이 세션의 비용 증가가 없음 — --usd 를 쓴다')
        usd, dur, how = own_usd / span * a.minutes, a.minutes, f'현재 세션 속도(${own_usd/span*60:.1f}/시간)로 {a.minutes:g}분'
    else:
        usd = a.usd if a.usd is not None else a.agents * a.per_agent
        dur, how = a.duration, ('--usd' if a.usd is not None else f'{a.agents:g}개 × ${a.per_agent:g}')
    t5 = (usd / u5, usd / p75, usd / p25)                    # (중앙, 하, 상)
    t7 = (usd / seven[0], usd / seven[2], usd / seven[1]) if seven else None
    # 다른 세션
    unknown_rate = span < 10
    if unknown_rate:
        o_lo = o_mid = o_hi = 0.0
        notes.append(f'구간 기록이 {span:.0f}분뿐(10분 미만)이라 다른 세션 속도를 못 잼 — 합산은 하한(0)')
        rate_txt = '속도 불명'
    else:
        own_pts = own_usd / u5
        if delta < 3:
            r_lo, r_mid, r_hi = 0.0, 0.0, max(0.0, delta + 1 - own_pts) / span
            rate_txt = f'약 0~{r_hi:+.2f}p/분(구간 {span:.0f}분 계정 +{delta:.0f}p 로 3p 미만이라 범위로만)'
        else:
            r_lo, r_mid, r_hi = (max(0.0, delta + k - own_pts) / span for k in (-1, 0, 1))
            rate_txt = f'{r_mid:+.2f}p/분(구간 {span:.0f}분 계정 +{delta:.0f}p 에서 이 세션 몫 제외, 범위 {r_lo:+.2f}~{r_hi:+.2f})'
        o_lo, o_mid, o_hi = r_lo * dur, r_mid * dur, r_hi * dur
    o7 = tuple(x * u5 / seven[0] for x in (o_mid, o_lo, o_hi)) if seven else None
    cur5, cur7 = last['f'], last['s']
    e5 = (cur5 + t5[0] + o_mid, cur5 + t5[1] + o_lo, cur5 + t5[2] + o_hi)
    e7 = (cur7 + t7[0] + o7[0], cur7 + t7[1] + o7[1], cur7 + t7[2] + o7[2]) if seven and cur7 is not None else None
    pl_, (ask5, ask7) = ask_levels()
    v5 = judge(cur5, e5[0], e5[2], ask5)
    v7 = judge(cur7, e7[0], e7[2], ask7) if e7 else None
    verdict = max((v for v in (v5, v7) if v), key=VERDICT_ORDER.index)
    left_min = (last['fr'] - now) / 60
    if dur > left_min:
        notes.append(f'작업({dur:.0f}분)이 5h 리셋({left_min:.0f}분 뒤) 뒤까지 간다 — 5h 예상은 리셋 전까지로만 읽는다(보수적으로 전부 더함)')
    sh = opus_share(recs, now)
    if sh is not None and sh >= OPUS_WARN:
        notes.append(f'최근 6시간 비용의 {sh:.0%} 가 opus — 보정은 sonnet 위주에서만 검증됐다, % 가 더 크게 나올 수 있음')
    if seven is None:
        notes.append('7d 보정 없음 — 7d 예상은 내지 않음')
    if pl != 'max_5x':
        notes.append(f'플랜 {pl} 보정은 사용자가 고정했거나 자동으로 충분히 쌓인 값(계획상 max_5x 우선)')
    lower = '약 ' if age > STALE_S else ''
    out = dict(plan=pl, input=how, usd=round(usd, 2), duration_min=dur, verdict=verdict, verdict_text=VERDICT_TEXT[verdict],
               calibration=dict(usd_per_pt_5h=round(u5, 3), p25=round(p25, 3), p75=round(p75, 3), windows=five[3], pinned=five[4], updated=(ent or {}).get('updated')),
               task_5h_pts=[round(x, 1) for x in t5], others_5h_pts=[round(x, 1) for x in (o_mid, o_lo, o_hi)], others_rate_known=not unknown_rate,
               now_5h=cur5, end_5h=[round(x, 1) for x in e5], ask_5h=ask5, verdict_5h=v5,
               now_7d=cur7, end_7d=[round(x, 1) for x in e7] if e7 else None, ask_7d=ask7, verdict_7d=v7,
               five_hour_resets=last['fr'], record_age_s=round(age), stale=age > STALE_S, notes=notes)
    if not a.no_log:
        try:
            with open(estimates_path(a), 'a') as fh:    # 숫자만. 작업 설명·세션 ID·경로는 남기지 않는다(D-9)
                fh.write(json.dumps(dict(t=round(now), plan=pl, input='usd' if a.usd is not None else 'agents' if a.agents is not None else 'minutes',
                                         usd=round(usd, 2), duration_min=round(dur, 1), task5=[round(x, 2) for x in t5], others5=[round(x, 2) for x in (o_mid, o_lo, o_hi)],
                                         end5=[round(x, 2) for x in e5], f=cur5, s=cur7, fr=last['fr'], sr=last['sr'], verdict=verdict, calib_n=five[3])) + '\n')
        except OSError as e:
            notes.append(f'예측 기록을 못 남김({e})')
    if a.json:
        print(json.dumps(out, ensure_ascii=False)); return 0
    up = f'작업 예상 ${usd:.0f}({how}) ≈ 5h +{t5[0]:.0f}p(범위 +{t5[1]:.0f}~+{t5[2]:.0f}p)' + (f' · 7d +{t7[0]:.0f}p' if t7 else '')
    print(f"{up} — 보정 {pl} ${u5:.2f}/p(창 {five[3]}개{', 고정값' if five[4] else ''}, 갱신 {(ent or {}).get('updated', '?')[:10]})")
    print(f"다른 세션 현재 속도 {rate_txt} → " + ('합산 못 함(아래 예상은 다른 세션 몫을 뺀 하한)' if unknown_rate else f"작업 {dur:.0f}분이면 +{o_mid:.0f}p(범위 +{o_lo:.0f}~+{o_hi:.0f}p)") + f"   (기록 {age/60:.0f}분 전)")
    print(f"5h {cur5:.0f}% → 예상 종료 {lower}{e5[0]:.0f}%(범위 {e5[1]:.0f}~{e5[2]:.0f}%), 리셋 {hhmm(last['fr'])}까지 {left_min/60:.1f}시간. 확인선 {ask5}%: {VERDICT_TEXT[v5]}")
    if e7:
        print(f"7d {cur7:.0f}% → 약 {e7[0]:.0f}%(범위 {e7[1]:.0f}~{e7[2]:.0f}%, 확인선 {ask7}%): {VERDICT_TEXT[v7]}")
    print(f"판정: {VERDICT_TEXT[verdict]}")
    for n_ in notes:
        print('  ※ ' + n_)
    return 0


def review(a):
    """지난 예측을 실제와 맞댄다. 예측 시각 + 작업 시간 시점의 관측 5h % 에서 예측 시점 %를 뺀 값이 실제 증가."""
    now = a.now if a.now is not None else time.time()
    try:
        ests = [json.loads(l) for l in open(estimates_path(a)) if l.strip()]
    except OSError:
        ests = []
    except ValueError:
        return fail(a, f'{estimates_path(a)} 이 깨짐')
    if not ests:
        msg = '예측 기록 없음(estimate 를 쓴 뒤에 쌓인다)'
        print(json.dumps({'rows': [], 'summary': msg}, ensure_ascii=False) if a.json else msg); return 0
    try:
        recs = all_records(a.file)
    except OSError as e:
        return fail(a, f'{a.file} 을 읽지 못함 ({e})')
    by = {}
    for r in recs:
        by.setdefault(r['fr'], []).append(r)
    rows = []
    for e in ests:
        target = e['t'] + e['duration_min'] * 60
        row = dict(t=e['t'], input=e['input'], usd=e['usd'], pred=round(e['end5'][0] - e['f'], 1), pred_lo=round(e['end5'][1] - e['f'], 1), pred_hi=round(e['end5'][2] - e['f'], 1))
        if now < target:
            row['status'] = 'pending'
        else:
            cutoff = min(target, e['fr'])
            cand = [r for r in by.get(e['fr'], []) if r['t'] <= cutoff]
            if not cand or cutoff - cand[-1]['t'] > 900:
                row['status'] = 'no-data'
            else:
                row['actual'] = cand[-1]['f'] - e['f']
                row['status'] = 'truncated' if e['fr'] < target else 'done'
                if row['status'] == 'done':
                    row['err'] = round((row['actual'] - row['pred']) / max(row['pred'], 1.0), 3)
                    row['in_range'] = row['pred_lo'] - 1 <= row['actual'] <= row['pred_hi'] + 1     # 정수 % 반올림 ±1
        rows.append(row)
    done = [r for r in rows if r['status'] == 'done']
    summ = dict(total=len(rows), done=len(done), pending=sum(r['status'] == 'pending' for r in rows),
                excluded=sum(r['status'] in ('no-data', 'truncated') for r in rows))
    if done:
        summ['median_err'] = round(statistics.median(r['err'] for r in done), 3)
        summ['median_abs_err'] = round(statistics.median(abs(r['err']) for r in done), 3)
        summ['in_range'] = round(sum(r['in_range'] for r in done) / len(done), 3)
    summ['verdict'] = ('판정 보류(비교된 예측 20건 미만)' if len(done) < 20 else
                       '유지 기준 충족' if abs(summ['median_err']) <= 0.30 and summ['in_range'] >= 0.60 else '유지 기준 미달 — 보정·입력 방식 재검토')
    if a.json:
        print(json.dumps(dict(rows=rows, summary=summ), ensure_ascii=False)); return 0
    for r in rows[-a.last:]:
        tt = dt.datetime.fromtimestamp(r['t']).strftime('%m-%d %H:%M')
        tail = f"실제 +{r['actual']:.0f}p, 오차 {r['err']:+.0%}, 범위 {'안' if r['in_range'] else '밖'}" if r['status'] == 'done' else r['status']
        print(f"{tt} {r['input']} ${r['usd']:.0f}: 예측 +{r['pred']:.0f}p({r['pred_lo']:.0f}~{r['pred_hi']:.0f}) → {tail}")
    print(f"요약: 기록 {summ['total']}건 중 비교 {summ['done']}건(대기 {summ['pending']}·제외 {summ['excluded']})"
          + (f", 오차 중앙값 {summ['median_err']:+.0%}(절대 {summ['median_abs_err']:.0%}), 범위 안 {summ['in_range']:.0%}" if done else '') + f" — {summ['verdict']}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--file', default=FILE)
    ap.add_argument('--now', type=float, default=None, help=argparse.SUPPRESS)      # 시험용: 현재 시각(epoch 초) 고정
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('status'); p.add_argument('--json', action='store_true'); p.add_argument('--recent', type=float, default=30)
    p = sub.add_parser('watch')
    p.add_argument('--spike', type=float, default=5); p.add_argument('--window', type=float, default=10)
    p.add_argument('--levels', default='50,70,80,90'); p.add_argument('--poll', type=float, default=5)
    p.add_argument('--forecast', default='150,200'); p.add_argument('--forecast-min-elapsed', type=float, default=30)
    p.add_argument('--forecast-min-used', type=float, default=10)
    p = sub.add_parser('calibrate'); p.add_argument('--write', action='store_true'); p.add_argument('--quiet', action='store_true'); p.add_argument('--json', action='store_true')
    p.add_argument('--days', type=float, default=CAL_DAYS); p.add_argument('--since', default=None, help='창 시작 하한(ISO 시각). 기본 2026-10-28 KST')
    p = sub.add_parser('pin'); p.add_argument('--plan', default='max_5x'); p.add_argument('--five', type=float); p.add_argument('--seven', type=float); p.add_argument('--unpin', action='store_true')
    p = sub.add_parser('estimate'); p.add_argument('--json', action='store_true')
    p.add_argument('--usd', type=float); p.add_argument('--agents', type=float); p.add_argument('--per-agent', type=float); p.add_argument('--minutes', type=float)
    p.add_argument('--duration', type=float, default=60, help='--usd·--agents 일 때 작업이 걸릴 분(다른 세션 속도를 곱할 시간). 기본 60')
    p.add_argument('--interval', type=float, default=60, help='속도를 재는 최근 구간(분). 기본 60')
    p.add_argument('--exclude-session', default=os.environ.get('CLAUDE_CODE_SESSION_ID', ''), help='다른 세션 속도에서 뺄 현재 세션 ID(기본 CLAUDE_CODE_SESSION_ID)')
    p.add_argument('--no-log', action='store_true', help='예측을 limit-estimates.jsonl 에 남기지 않음')
    p = sub.add_parser('review'); p.add_argument('--json', action='store_true'); p.add_argument('--last', type=int, default=15)
    a = ap.parse_args()
    try:
        sys.exit({'status': status, 'watch': watch, 'calibrate': calibrate, 'pin': pin, 'estimate': estimate, 'review': review}[a.cmd](a))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
