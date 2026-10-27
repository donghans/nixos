#!/usr/bin/env python3
"""화면 정렬 시험 — 한글(2칸 폭)이 섞여도 표·범례·라벨-값 줄이 칸 수 기준으로 맞는지, 값이 다음 열에 붙지 않는지, 줄이 폭을 넘지 않는지 본다.
(f-string 의 :<n 은 글자 수 기준이라 한글 표가 어긋난다 — 실제 터미널 촬영에서 용어 탭·범례가 어긋난 것을 찾아 고쳤다.)"""
import os, re, sys, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE); DATA = os.path.dirname(ROOT)
for p in (ROOT, os.path.join(DATA, "_lib", "_uikit"), os.path.join(DATA, "..", "_data", "claude-skills", "donghans-host-resources", "scripts"), os.path.join(DATA, "procui"), os.path.join(DATA, "_lib", "_testkit")):
    sys.path.insert(0, p)
from rich.cells import cell_len
from rich.text import Text
import usagelive as lv
import uikit
import usageview as uv
import procscan as ps
from harness import checker
check, finish = checker()

def col(line, token):
    """line 에서 token 이 시작하는 **칸 위치**(한글 2칸)."""
    i = line.find(token)
    return None if i < 0 else cell_len(line[:i])

sm = lv.LiveSampler(slow_every=60); sm.sample(); time.sleep(1.1); s = sm.sample()
# 메모리 범례: GiB 숫자 열이 모든 줄에서 같은 칸에서 끝남
M = lv.render_mem(s, 70).plain.splitlines()
leg = [l for l in M if "■" in l]
ends = {cell_len(l[:re.search(r"[\d.]+ GiB\s+\d+%", l).start()] + re.search(r"[\d.]+ GiB", l).group(0)) for l in leg}
check("메모리 범례: 8줄의 GiB 숫자가 같은 칸에서 끝남(한글 이름 폭 보정)", len(leg) == 8 and len(ends) == 1, ends)
pct_cols = {cell_len(l[:l.rindex("%")]) for l in leg}
check("메모리 범례: 퍼센트 열도 같은 칸", len(pct_cols) == 1, pct_cols)
# 압박 박스: some 열이 메모리/CPU/IO 줄에서 같은 칸
P = [l for l in lv.render_pressure(s).plain.splitlines() if " some " in l and ("메모리" in l or "CPU" in l or "IO" in l)]
check("압박 박스: 메모리·CPU·IO 줄의 some 열이 같은 칸", len({col(l, "some") for l in P}) == 1 and len(P) == 3, [col(l, "some") for l in P])
# 세션 박스: PSS 열이 모든 줄에서 같은 칸(이름에 한글이 있어도)
fake = dict(s, sessions=[(500.0, 1, "프로젝트한글이름", 3, 0.0, 1.0, "claude", dict(name="한글 세션 이름", sid="abcd1234", status="busy", sub=dict(running=[], done=0, last_end=None)), {}),
                          (300.0, 2, "nixos", 1, 0.0, 1.0, "claude", dict(name="ascii-session", sid="efgh5678", status="idle", sub=dict(running=[], done=0, last_end=None)), {}),
                          (200.0, 3, "x", 1, 0.0, 1.0, "claude", None, {})])
R = [l for l in lv.render_sessions(fake).plain.splitlines() if "PSS" in l and "합" not in l]
check("세션 박스: 한글 이름·상태가 섞여도 PSS 열이 같은 칸", len(R) == 3 and len({col(l, "PSS") for l in R}) == 1, [col(l, "PSS") for l in R])
# 앱 CPU 줄: 한 줄이 폭을 넘지 않음
fk = dict(s, apps_measured=True, apps=[dict(app="아주아주긴한글앱이름입니다" * 3, n=12, cpu=55.5, rss=123 << 20), dict(app="node", n=3, cpu=1.0, rss=1 << 20)])
w = 60
T = [l for l in lv.render_top(fk, w).plain.splitlines() if "MiB" in l and "%" in l and "개" in l]
check("상위 소비자: 앱 줄이 박스 폭(60칸)을 넘지 않고 개수 열이 같은 칸", T and all(cell_len(l) <= w for l in T) and len({col(l, "개") + 0 for l in T}) <= 2, [(cell_len(l), col(l, "개")) for l in T])
# 도움말의 용어 절(예전 용어 탭): 이름 칸이 맞고 설명 줄바꿈이 들여쓰기되며 어떤 줄도 폭을 넘지 않음
for width in (60, 100, 150):
    G = uikit.terms_text(uv.GLOSSARY, width).plain.splitlines()
    kw = max(cell_len(k) for k, _ in uv.GLOSSARY) + 2
    dw = max(20, width - kw - 2)
    starts, firsts = set(), []
    for k, d in uv.GLOSSARY:
        ln = next((l for l in G if l.startswith(" " + k + " ")), None)
        if ln is not None:
            firsts.append(ln)
            starts.add(col(ln, uikit.wrap_cells(d, dw)[0]))
    conts = [l for l in G if l.startswith(" " * (1 + kw)) and l.strip()]
    check(f"도움말 용어(폭 {width}): 항목마다 설명이 같은 칸(1+이름 칸)에서 시작, 줄바꿈 줄은 같은 칸으로 들여쓰기, 줄 길이 ≤ 폭", len(firsts) == len(uv.GLOSSARY) and starts == {1 + kw} and all(cell_len(l) <= width for l in G) and (width >= 100 or conts), (len(firsts), starts, max(cell_len(l) for l in G)))
check("wrap_cells: 한글 폭 기준으로 끊고 빈 입력도 안전", all(cell_len(x) <= 10 for x in uikit.wrap_cells("한글로 된 긴 문장을 열 칸 폭으로 줄바꿈 합니다", 10)) and uikit.wrap_cells("", 10) == [""] or uikit.wrap_cells("", 10) == [])
# 라벨-값 줄: 값이 칸을 넘어도 노트에 붙지 않음
t = Text(); uv._line(t, "범위", "10-19 14:18 ~ 10-26 14:18", "7일 · 지금까지", lw=14, vw=14)
check("라벨-값 줄: 값이 칸 폭을 넘어도 뒤에 한 칸 이상 띄움(「14:187일」 방지)", "14:18 7일" in t.plain, t.plain)
t = Text(); uv._line(t, "문맥 전환·인터럽트", "100771/s · 123188/s")
check("라벨-값 줄: 긴 한글 라벨도 값과 붙지 않음", re.search(r"인터럽트 +\d", t.plain) is not None, t.plain)
t = Text(); uv._line(t, "패키지 전력량", "1945.65 Wh", "측정 · 적분", lw=18, vw=10)
check("라벨-값 줄: 값이 칸 폭과 같아도 노트와 띄움(「Wh측정」 방지)", "Wh 측정" in t.plain, t.plain)
check("short_dur: 분·시간·일 단위 전환", uv.short_dur(600) == "10분" and uv.short_dur(7200) == "2.0시간" and uv.short_dur(259997) == "3.0일" and uv.short_dur(None) == "0분")
# procctl/procui 표: 한글 그룹 이름이 섞여도 열이 같은 칸
rows = ["컨테이너·VM", "내 작업", "시스템", "claude #123", "아주아주아주아주아주긴한글그룹이름입니다아아아"]
lines = [f"  {ps.fit(r, 34)} {5:>4}개  CPU" for r in rows]
check("procctl 그룹 표: 한글/영문 그룹 이름이 섞여도 「개」 열이 같은 칸이고 긴 이름은 …로 잘림", len({col(l, "개") for l in lines}) == 1 and all("…" in l for l in lines[-1:]), [col(l, "개") for l in lines])
check("procscan.cells/fit: 한글 2칸·전각·결합문자 0칸, fit 은 항상 n 칸", ps.cells("가나") == 4 and ps.cells("ＡＢ") == 4 and ps.cells("é") == 1 and all(ps.cells(ps.fit(x, 12)) == 12 for x in ("a", "한글", "아주긴한글이름입니다정말로")))
finish("layout")
