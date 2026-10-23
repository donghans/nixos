#!/usr/bin/env python3
"""세션 복원 수집기(읽기 전용). 사용: resume.py [ID또는접두] [--n 15] [--no-git] [--list]
 - ID 있음: ~/.claude/handoffs/<ID>.json 으로 저장소·문서를 찾는다(접두 일치 허용). 기록이 없으면 트랜스크립트만으로 사용자 메시지를 복원한다.
 - ID 없음: 현재 저장소에 등록된 가장 최근 인수인계, 없으면 저장소의 최신 HANDOFF-*.md.
 - --list: 등록된 인수인계 목록.
 저장소에 실행 파일 `.claude/resume-extra` 가 있으면 저장소 루트에서 실행해 그 출력을 덧붙인다(프로젝트 전용 사실 수집)."""
import argparse, glob, json, os, re, subprocess, sys, time

ap = argparse.ArgumentParser()
ap.add_argument('id', nargs='?'); ap.add_argument('--n', type=int, default=15)
ap.add_argument('--no-git', action='store_true'); ap.add_argument('--list', action='store_true')
a = ap.parse_args()
HD = os.path.expanduser('~/.claude/handoffs')

def sh(*cmd, cwd=None):
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return (r.stdout + r.stderr).strip()

def load_all():
    out = []
    for p in glob.glob(HD + '/*.json'):
        try: out.append(json.load(open(p)))
        except Exception: pass
    return sorted(out, key=lambda r: r.get('created', ''), reverse=True)


def from_db(prefix):
    """로컬 기록이 없으면 공유 저장소(donghans → Postgres)에서 인수인계를 받아 캐시에 푼다(다른 머신에서 만든 인수인계)."""
    cache = os.path.expanduser('~/.claude/handoffs-cache')
    out = sh('donghans', 'handoff', 'get', prefix, '--out', cache)
    first = out.splitlines()[0] if out else ''
    try: d = json.loads(first)
    except Exception: return None
    top = sh('git', 'rev-parse', '--show-toplevel')
    here = sh('git', '-C', top, 'remote', 'get-url', 'origin') if top else ''
    repo = d.get('repo_root') if d.get('repo_root') and os.path.isdir(d['repo_root']) else (top or '')
    return {'id': d['id'], 'repo': repo, 'doc': os.path.join(cache, d['doc']), 'branch': d.get('branch'), 'head': d.get('head'),
            'created': (d.get('created') or '')[:19], 'note': f"(공유 저장소에서 받음 · 작성 머신 {d.get('host')} · 저장소 {d.get('repo_url')})" + (' ' + d['note'] if d.get('note') else '')}

recs = load_all()
if a.list:
    for r in recs: print(f"{r['id']}  {r['created'][:16]}  {r['repo']}  {r.get('note','')}")
    sys.exit(0 if recs else 1)

rec = None
if a.id:
    m = [r for r in recs if r['id'].startswith(a.id)]
    if len(m) > 1: sys.exit('접두가 여러 기록과 일치: ' + ', '.join(r['id'] for r in m))
    rec = m[0] if m else from_db(a.id)
else:
    top = sh('git', 'rev-parse', '--show-toplevel') or os.getcwd()
    rec = next((r for r in recs if r['repo'] == top), None)
    if not rec:
        hs = sorted(glob.glob(top + '/**/HANDOFF-*.md', recursive=True), key=os.path.getmtime)
        if hs: rec = {'id': '', 'repo': top, 'doc': hs[-1], 'created': '', 'note': '(등록 기록 없음 — 최신 HANDOFF 파일로 대체)'}
if not rec:
    print('## 인수인계 기록 없음' + (f' (ID {a.id})' if a.id else ''))
    print('등록 목록: resume.py --list. 기록이 없어도 트랜스크립트가 있으면 사용자 메시지만 복원한다.')

def show_instructions(cwd, sections):
    """프로젝트 지침을 `donghans instr show` 로 읽는다 — 먼저 공유 저장소와 맞춘(최신화) 뒤 해당 절만 보인다(접속 실패면 캐시를 「낡았을 수 있음」으로 표시).
    명령을 못 쓰면 None(→ 아래에서 파일을 직접 읽는다)."""
    try:
        r = subprocess.run(['donghans', 'instr', 'show', *[x for s in sections for x in ('--section', s)]], cwd=cwd, capture_output=True, text=True, timeout=15)
        return r.stdout if r.returncode == 0 else None
    except Exception:
        return None


if rec:
    repo = rec['repo']
    print('## 인수인계 기록')
    for k in ('id', 'created', 'repo', 'doc', 'branch', 'head', 'note'):
        if rec.get(k): print(f'{k:8}: {rec[k]}')
    if not os.path.isdir(repo): print('!! 저장소 경로가 없다 — 다른 머신이거나 이동됨')
    elif not os.path.isfile(rec['doc']): print('!! 문서 파일이 없다 — 삭제/이동됨 (git log 로 추적)')
    else:
        print(f"문서 수정: {time.strftime('%m-%d %H:%M', time.localtime(os.path.getmtime(rec['doc'])))}")
    if os.path.isdir(repo) and not a.no_git:
        print('\n## git (지금 상태)')
        print('HEAD  :', sh('git', 'log', '-1', '--format=%h %s', cwd=repo))
        print('브랜치:', sh('git', 'branch', '--show-current', cwd=repo) or '(detached HEAD)')
        st = sh('git', 'status', '--short', cwd=repo).splitlines()
        print('미커밋:', len(st), '건'); [print('  ', l) for l in st[:10]]
        if rec.get('head'):
            n = sh('git', 'rev-list', '--count', f"{rec['head']}..HEAD", cwd=repo)
            print(f"인수인계 시점({rec['head']}) 이후 커밋:", n if n.isdigit() else '? (SHA 없음)')
        for ref in sh('git', 'for-each-ref', '--format=%(upstream:short)', 'HEAD', cwd=repo).splitlines()[:1]:
            if ref: print(f'{ref} 대비 앞선 커밋:', sh('git', 'rev-list', '--count', f'{ref}..HEAD', cwd=repo), '(푸시는 사용자 허가 필요)')
        wt = sh('git', 'worktree', 'list', '--porcelain', cwd=repo)
        un = []
        for blk in wt.split('\n\n'):
            d = dict(l.split(' ', 1) for l in blk.splitlines() if ' ' in l)
            br = d.get('branch', '').replace('refs/heads/', '')
            if br and d.get('worktree') != repo and subprocess.run(['git', 'merge-base', '--is-ancestor', br, 'HEAD'], cwd=repo).returncode != 0:
                un.append(f"- {br} ({len(sh('git','log','--oneline','HEAD..'+br,cwd=repo).splitlines())}커밋 앞) {d.get('worktree')}")
        print('미병합 워크트리 브랜치:', '(없음)' if not un else ''); [print(x) for x in un]
    shown = show_instructions(repo, ['resume 할 때']) if os.path.isdir(repo) else None   # 읽기는 명령 경유 — 최신화 후 「resume 할 때」 절만(생략한 절은 안내됨)
    if shown:
        print('\n' + shown.rstrip())
    elif shown is None:   # donghans 명령을 못 쓰면 파일을 그대로 읽는다(낡았을 수 있음)
        for nm, why in (('donghans-instructions.md', '추가 지침 — 기본 절차에 더해 적용'), ('donghans-override.md', '오버라이드 — 충돌하는 기본 절차보다 우선')):
            pf = os.path.join(repo, '.claude', nm)
            if os.path.isfile(pf):
                print(f'\n## 프로젝트 지침: .claude/{nm} ({why}) — ⚠ donghans 명령을 못 써서 로컬 파일을 직접 읽음, 낡았을 수 있음'); print(open(pf, errors="ignore").read().strip())
    dd = os.path.splitext(rec['doc'])[0].replace('HANDOFF-', '')  # 상세 문서 디렉터리: <doc 디렉터리>/<세션ID>/
    dd = os.path.join(os.path.dirname(rec['doc']), rec.get('id') or os.path.basename(dd))
    if os.path.isdir(dd):
        print(f'\n## 상세 문서 ({dd}) — 인덱스 표의 「언제 읽나」에 맞춰 필요한 것만 열 것')
        for fn in sorted(os.listdir(dd)): print(f'- {fn} ({os.path.getsize(os.path.join(dd, fn))}B)')
    ex = os.path.join(repo, '.claude', 'resume-extra')
    if os.path.isfile(ex) and os.access(ex, os.X_OK):
        print('\n## 프로젝트 추가 사실 (.claude/resume-extra)'); print(sh(ex, cwd=repo))


# 계정 전체 사용량 스냅샷 — 5h/7d 한도는 계정 공통이지만 각 세션의 상태 표시줄이 그릴 때만 기록된다.
# 그러니 세션별 값이 아니라 *전체에서 가장 최근* 기록을 보이고, 나이를 같이 적는다(다른 세션이 올린 만큼은 아직 반영 전일 수 있다).
lp = os.path.expanduser('~/.local/share/claude-otel/limits.jsonl')
if os.path.isfile(lp):
    last = None
    for l in open(lp, errors='ignore'):
        try: d = json.loads(l)
        except Exception: continue
        if (d.get('five_hour') or {}).get('used_percentage') is not None: last = d
    if last:
        try: age = int(time.time() - time.mktime(time.strptime(last['ts'][:19], '%Y-%m-%dT%H:%M:%S')))
        except Exception: age = -1
        print('\n## 사용량 스냅샷 (계정 전체, 가장 최근 기록)')
        print(f"5h {last['five_hour']['used_percentage']}% · 7d {(last.get('seven_day') or {}).get('used_percentage')}% · 기록 {last['ts'][11:19]} ({age // 60}분 {age % 60}초 전) · 기록한 세션 {str(last.get('session_id'))[:8]}")
        print('※ 스냅샷이다 — 기록은 어느 세션이든 상태 표시줄이 갱신될 때만 남고, 동시에 도는 다른 세션이 올린 만큼은 다음 갱신 전까지 안 보인다. 사용자에게는 「약 N% 이상(스냅샷 기준)」으로 말하고, 한도 판단은 감시기(claude-limit-watch, 전 세션 기록 기준)와 사용자가 보는 /usage 를 우선한다.')

# 트랜스크립트의 사용자 메시지
sid = (rec or {}).get('id') or a.id or ''
SKIP = ('<system-reminder', '<task-notification', '<command-name>', '<local-command', '[SYSTEM NOTIFICATION', '<cross-session-message', 'This session is being continued')
if sid:
    fs = glob.glob(os.path.expanduser(f'~/.claude/projects/*/{sid}*.jsonl'))
    print('\n## 그 세션에서 사용자가 직접 보낸 메시지 (마지막 %d개)' % a.n)
    if not fs:
        print('(로컬 트랜스크립트 없음 — 공유 저장소에서 조회)')
        if re.fullmatch(r'[0-9a-f-]{6,36}', sid):
            print(sh('donghans', 'ctx', 'sql', f"select to_char(ts,'MM-DD HH24:MI') ts, left(text,500) prompt from messages where session_id like '{sid}%' and kind='prompt' and text not like '<%' order by ts desc limit {a.n}"))
    for f in fs[:1]:
        msgs = []
        for l in open(f, errors='ignore'):
            try: d = json.loads(l)
            except Exception: continue
            if d.get('type') != 'user' or d.get('isMeta') or d.get('isSidechain'): continue
            c = (d.get('message') or {}).get('content')
            t = (c if isinstance(c, str) else ' '.join(x.get('text', '') for x in c if isinstance(x, dict) and x.get('type') == 'text')).strip()
            if t and not any(t.startswith(s) for s in SKIP): msgs.append(((d.get('timestamp') or '')[:16], t))
        print(f'(전체 {len(msgs)}개 중 — 트랜스크립트 {os.path.basename(f)})')
        for ts, t in msgs[-a.n:]: print(f'- [{ts}] {t[:500]}')
print('\n※ 위는 사실 수집이다. 문서(doc)는 그 시점의 관찰이므로 git 상태와 어긋나면 어긋남을 보고하라.')
