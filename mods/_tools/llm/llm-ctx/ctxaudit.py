#!/usr/bin/env python3
"""ctxaudit — 전제 감사관(donghans-plan 점검 항목 9) 보고의 기계 검사·채점. 감사관 자체는 LLM 이고, 이 파일은 **호출자 쪽** 도구다.
설계·결정: `donghans ctx doc read --project nixos plan llm-trust/06-p4-premise-auditor` (§5 정본 경로, §6 대조군 시험).

  ctxaudit.py check <보고서.md> [--texts DIR] [--json]       보고된 인용마다 원문(`ctx msg <uuid> --all`)과 대조: 위조 인용 수
  ctxaudit.py score --key <정답표.json> <보고서.md>… [--texts DIR] [--json]   오탐률·재현율·위조 인용·꼬리 읽기, 반복 간 불일치

보고서 형식(감사관에게 요구): 마크다운 표 한 행 = 전제 하나. 첫 칸은 `[<전제 id>]` 로 시작(채점용), 둘째 칸이 a/b/c(또는 확인 불가),
셋째 칸에 uuid(8자 이상 hex)와 인용(「…」·“…”·"…"). 인용 일치는 `ctxcards.quote_matches` 보다 **엄격**하다 — `…` 조각이 보고된 순서대로 나와야 통과하고,
`<pasted_content>` 블록 안 인용은 따로 표시한다. 그래도 약한 검사다: 「위조 0건」은 인용의 존재만 말하며 a/b/c 분류가 맞다는 증명이 아니다.
`--texts DIR` 는 `<uuid앞8자>.txt` 에 원문 전체를 둔 폴더(오프라인·시험용). 없으면 `donghans ctx msg <uuid> --all` 로 읽는다.
"""
import argparse
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ctxcards as cx  # noqa: E402  (quote_matches — 카드 검사와 같은 기준의 하한)

UUID_TOKEN = re.compile(r"(?<![0-9a-fA-F-])([0-9a-f]{8}(?:-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})?|[0-9a-f]{9,36})(?![0-9a-fA-F-])")
QUOTE_RES = (re.compile(r"「([^」]+)」"), re.compile(r"“([^”]+)”"), re.compile(r'"([^"]+)"'))
PID = re.compile(r"^\s*\[?\s*([A-Za-z]+\d*-\d+[A-Za-z]?)\s*\]?")
PASTE = re.compile(r"<pasted_content\b[^>]*>(.*?)(?:</pasted_content>|\Z)", re.S)
CLASSES = ("a", "b", "c")


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", t or "").strip()


def _parts(quote: str) -> list:
    return [p for p in (norm(x) for x in re.split(r"…|\.\.\.", quote or "")) if len(p) >= 2]


def ordered_match(quote: str, text: str) -> bool:
    """quote_matches 보다 엄격: `…`·`...` 로 나눈 조각이 text 에 **보고된 순서대로** 겹치지 않게 나타나야 한다."""
    hay, pos, parts = norm(text), 0, _parts(quote)
    if not parts:
        return False
    for p in parts:
        i = hay.find(p, pos)
        if i < 0:
            return False
        pos = i + len(p)
    return True


def split_paste(text: str) -> tuple:
    """(블록 밖 글, 블록 안 글). 닫는 태그가 없으면 끝까지 블록으로 본다."""
    inside = " ".join(m.group(1) for m in PASTE.finditer(text or ""))
    return PASTE.sub(" ", text or ""), inside


def locate(quote: str, text: str) -> str:
    """인용이 사용자 본인 글(outside)에 있나, 붙여넣은 블록 안(inside)인가, 둘에 걸쳤나(mixed), 순서가 어긋났나(order), 없나(none)."""
    if not cx.quote_matches(quote, text):
        return "none"
    if not ordered_match(quote, text):
        return "order"
    out, ins = split_paste(text)
    if ordered_match(quote, out):
        return "outside"
    if ordered_match(quote, ins):
        return "inside"
    return "mixed"


def extract_quotes(cell: str) -> list:
    found = []
    for rx in QUOTE_RES:
        found += [m.group(1) for m in rx.finditer(cell or "")]
    return [q for q in found if len(norm(q)) >= 2]


def split_row(line: str) -> list:
    s = line.strip()
    if not s.startswith("|"):
        return []
    s = s.strip("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", s)]


def parse_report(md: str) -> list:
    """표 행 → {pid, cls, uuids, quotes, raw}. 머리·구분선 행은 건너뛴다. 둘째 칸이 a/b/c·확인 불가가 아니면 cls 는 None."""
    rows = []
    for line in md.splitlines():
        cells = split_row(line)
        if len(cells) < 3 or set("".join(cells)) <= set("-: "):
            continue
        m = PID.match(cells[0])
        c2 = cells[1].strip().lower().strip("*` ")
        cls = c2[0] if c2[:1] in CLASSES and (len(c2) == 1 or c2[1] in " (:：-—·,") else ("?" if "확인" in c2 else None)
        if cls is None and not m:
            continue                                   # 표 머리 등
        rest = " | ".join(cells[2:])
        uuids = []
        for u in UUID_TOKEN.findall(rest):
            if u not in uuids:
                uuids.append(u)
        rows.append({"pid": m.group(1) if m else None, "cls": cls, "uuids": uuids, "quotes": extract_quotes(rest), "raw": line})
    return rows


def make_fetch(texts_dir: str = None):
    """fetch(uuid) → ("ok", 본문) | ("none",) | ("ambiguous", [..])"""
    def fetch(u):
        if texts_dir:
            for name in (u[:8] + ".txt", u + ".txt"):
                p = os.path.join(texts_dir, name)
                if os.path.exists(p):
                    return ("ok", open(p, encoding="utf-8").read())
            return ("none",)
        r = subprocess.run(["donghans", "ctx", "msg", u, "--all"], capture_output=True, text=True, timeout=60)
        out = r.stdout
        if r.returncode != 0 or not out.strip():
            return ("none",)
        if out.lstrip().startswith("# ") and "후보" not in out.split("\n", 1)[0]:
            return ("ok", out.split("\n", 1)[1] if "\n" in out else "")
        return ("ambiguous", [out[:200]])
    return fetch


def check_rows(rows: list, fetch) -> list:
    """인용마다 {pid, uuid, quote, status}. status: 일치(outside) · 블록 안 · 일부 블록 걸침 · 순서 어긋남 · 미일치 · 메시지 없음 · 모호 · uuid 없음.
    무효(위조로 세는 것) = 미일치·순서 어긋남·메시지 없음·uuid 없음. 한 인용에 uuid 가 여럿이면 어느 하나의 본문에서라도 일치하면 그 결과를 쓴다."""
    out, cache = [], {}
    for r in rows:
        for q in r["quotes"]:
            if not r["uuids"]:
                out.append({"pid": r["pid"], "uuid": None, "quote": q, "status": "uuid 없음"})
                continue
            best, seen_text = None, False
            for u in r["uuids"]:
                if u not in cache:
                    cache[u] = fetch(u)
                f = cache[u]
                if f[0] == "ambiguous":
                    best = best or ("모호", u)
                    continue
                if f[0] == "none":
                    best = best or ("메시지 없음", u)
                    continue
                seen_text = True
                loc = locate(q, f[1])
                label = {"outside": "일치", "inside": "블록 안", "mixed": "일부 블록 걸침", "order": "순서 어긋남", "none": "미일치"}[loc]
                if best is None or best[0] in ("모호", "메시지 없음") or loc == "outside":
                    best = (label, u)
                if loc == "outside":
                    break
            out.append({"pid": r["pid"], "uuid": best[1], "quote": q, "status": best[0]})
    return out


INVALID = ("미일치", "순서 어긋남", "메시지 없음", "uuid 없음")


def summarize_check(res: list) -> dict:
    s = {"total": len(res), "invalid": [x for x in res if x["status"] in INVALID]}
    for k in ("일치", "블록 안", "일부 블록 걸침", "모호"):
        s[k] = sum(1 for x in res if x["status"] == k)
    s["forged"] = len(s["invalid"])
    return s


# ---------------------------------------------------------------- 채점
def score(key: dict, rows: list, fetch=None) -> dict:
    """key = {"premises": {pid: {"group": "N"|"P"|"H", "defect": bool, "tail": "꼬리 요청 문구(H 만, 선택)"}}, "thresholds": {…}(선택)}.
    같은 pid 의 행이 여럿이면 하나라도 b/c 이면 지적으로 본다. 보고에 없는 전제는 「누락」(오탐·재현율 분모에서 빼지 않고 따로 센다 — 누락은 못 잡은 것으로 센다)."""
    prem = key["premises"]
    by = {}
    for r in rows:
        if r["pid"]:
            by.setdefault(r["pid"], []).append(r)
    flagged, missing = set(), []
    for pid in prem:
        rs = by.get(pid)
        if not rs:
            missing.append(pid)
        elif any(r["cls"] in ("b", "c") for r in rs):
            flagged.add(pid)
    n_ids = [p for p, v in prem.items() if v["group"] == "N"]
    d_ids = [p for p, v in prem.items() if v.get("defect")]
    fp = [p for p in n_ids if p in flagged]
    tp = [p for p in d_ids if p in flagged]
    tails = [p for p, v in prem.items() if v.get("tail")]
    tail_ok = [p for p in tails if any(ordered_match(prem[p]["tail"], r["raw"]) or norm(prem[p]["tail"]) in norm(r["raw"]) for r in by.get(p, []))]
    res = {"premises": len(prem), "missing": missing, "flagged": sorted(flagged),
           "n_total": len(n_ids), "false_positive": fp, "fp_rate": (len(fp) / len(n_ids)) if n_ids else None,
           "defect_total": len(d_ids), "caught": tp, "missed": [p for p in d_ids if p not in flagged], "recall": (len(tp) / len(d_ids)) if d_ids else None,
           "tail_total": len(tails), "tail_read": tail_ok, "tail_rate": (len(tail_ok) / len(tails)) if tails else None,
           "unlabeled_rows": [r["raw"][:80] for r in rows if not r["pid"] or r["pid"] not in prem]}
    if fetch is not None:
        res["check"] = summarize_check(check_rows(rows, fetch))
    th = key.get("thresholds") or {"fp_rate": 0.10, "recall": 0.80, "forged": 0, "tail_rate": 1.0}
    verdict = {}
    if res["fp_rate"] is not None:
        verdict["fp_rate"] = res["fp_rate"] <= th["fp_rate"]
    if res["recall"] is not None:
        verdict["recall"] = res["recall"] >= th["recall"]
    if "check" in res:
        verdict["forged"] = res["check"]["forged"] <= th["forged"]
    if res["tail_rate"] is not None:
        verdict["tail_rate"] = res["tail_rate"] >= th["tail_rate"]
    res["meets"] = verdict
    return res


def disagreements(a: dict, b: dict) -> list:
    """두 반복의 지적(flagged) 집합이 다른 전제."""
    return sorted(set(a["flagged"]) ^ set(b["flagged"]))


# ---------------------------------------------------------------- CLI
def _fmt_check(s: dict) -> str:
    lines = [f"인용 {s['total']}건: 일치 {s['일치']} · 블록 안 {s['블록 안']} · 일부 블록 걸침 {s['일부 블록 걸침']} · 모호 {s['모호']} · 위조(무효) {s['forged']}"]
    for x in s["invalid"]:
        lines.append(f"  무효 [{x['pid'] or '-'}] {x['status']} uuid={x['uuid'] or '-'} 「{x['quote'][:60]}」")
    lines.append("※ 이 검사는 약하다: 위조 0건은 인용이 원문에 있다는 뜻일 뿐 a/b/c 분류가 맞다는 증명이 아니다.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("report"); c.add_argument("--texts"); c.add_argument("--json", action="store_true")
    s = sub.add_parser("score")
    s.add_argument("--key", required=True); s.add_argument("reports", nargs="+"); s.add_argument("--texts"); s.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    fetch = make_fetch(a.texts)
    if a.cmd == "check":
        rows = parse_report(open(a.report, encoding="utf-8").read())
        sm = summarize_check(check_rows(rows, fetch))
        print(json.dumps(sm, ensure_ascii=False, indent=1) if a.json else _fmt_check(sm))
        return 1 if sm["forged"] else 0
    key = json.load(open(a.key, encoding="utf-8"))
    results = [score(key, parse_report(open(p, encoding="utf-8").read()), fetch) for p in a.reports]
    out = {"runs": results, "disagree": disagreements(results[0], results[1]) if len(results) > 1 else []}
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        for p, r in zip(a.reports, results):
            pct = lambda v: "-" if v is None else f"{v:.0%}"
            print(f"{os.path.basename(p)}: 오탐률 {pct(r['fp_rate'])} ({len(r['false_positive'])}/{r['n_total']}) · 재현율 {pct(r['recall'])} ({len(r['caught'])}/{r['defect_total']})"
                  f" · 위조 인용 {r.get('check', {}).get('forged', '?')} · 꼬리 읽기 {pct(r['tail_rate'])} · 누락 전제 {len(r['missing'])}")
            print("  기준 충족:", ", ".join(f"{k}={'예' if v else '아니오'}" for k, v in r["meets"].items()) or "-", "(기준은 시작값 — 통과/실패 판정이 아니라 지적 사례를 하나씩 읽는다)")
        if out["disagree"]:
            print("반복 간 지적이 갈린 전제:", ", ".join(out["disagree"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
