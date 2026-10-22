#!/usr/bin/env python3
"""인수인계 등록기 — 현재 세션 ID 를 고유번호로 삼아 ~/.claude/handoffs/<ID>.json 에 (저장소, 문서)를 기록한다.
사용: register.py --doc <인수인계 문서 경로> [--repo <저장소 루트>] [--note "한 줄"]
다른 세션/다른 디렉터리에서 `/donghans-resume <ID>` 로 이 기록을 찾는다. 같은 세션에서 다시 실행하면 덮어쓴다(최신 문서가 정본)."""
import argparse, json, os, subprocess, sys, time

ap = argparse.ArgumentParser()
ap.add_argument('--doc', required=True); ap.add_argument('--repo'); ap.add_argument('--note', default='')
a = ap.parse_args()

def git(repo, *args):
    r = subprocess.run(['git', '-C', repo, *args], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ''

sid = os.environ.get('CLAUDE_CODE_SESSION_ID', '')
if not sid:
    sys.exit('CLAUDE_CODE_SESSION_ID 가 없다 — claude 세션 안에서 실행해야 한다.')
doc = os.path.abspath(a.doc)
if not os.path.isfile(doc):
    sys.exit(f'문서가 없다: {doc}')
repo = os.path.abspath(a.repo) if a.repo else (git(os.path.dirname(doc), 'rev-parse', '--show-toplevel') or os.getcwd())
rec = {'id': sid, 'repo': repo, 'doc': doc, 'cwd': os.getcwd(), 'branch': git(repo, 'branch', '--show-current') or '(detached)',
       'head': git(repo, 'rev-parse', '--short', 'HEAD'), 'created': time.strftime('%Y-%m-%dT%H:%M:%S%z'), 'note': a.note}
d = os.path.expanduser('~/.claude/handoffs'); os.makedirs(d, exist_ok=True)
with open(os.path.join(d, sid + '.json'), 'w') as f: json.dump(rec, f, ensure_ascii=False, indent=1)
# 공유 저장소(donghans)에도 올린다 — 다른 머신에서 `/donghans-resume <ID>` 가 되게. 실패해도 로컬 등록은 유효하다.
try:
    r = subprocess.run(['donghans', 'handoff', 'put', '--session', sid, '--doc', doc, '--note', a.note], capture_output=True, text=True, timeout=20)
    shared = (r.stdout.strip() or r.stderr.strip()).splitlines()[-1:] or ['(출력 없음)']
except Exception as e:
    shared = [f'공유 저장소 업로드 건너뜀: {type(e).__name__}']
print(f'등록됨: {sid}\n  저장소: {repo}\n  문서  : {doc}\n\n공유 저장소: {shared[0]}\n\n새 세션에서 이렇게 입력하세요:\n  /donghans-resume {sid}')
