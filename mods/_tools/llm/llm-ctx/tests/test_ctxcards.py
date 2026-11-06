#!/usr/bin/env python3
"""ctxcards 시험 — 카드 형식·파서·검증·인용 일치 검사·조회(여러 프로젝트)·판 이력(git)은 순수 함수 시험(DB 없음),
`donghans ctx card show|list` 는 임시 Postgres(합성 메시지)·임시 문서 저장소로 실제 프로세스를 돌린다. psycopg·postgres 가 없으면 CLI 부분만 건너뛴다."""
import json, os, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(ROOT)), "_lib", "testkit"))
from harness import checker
check, finish = checker()
import ctx_store as st
import ctxcards as cx

CID = "3f2a9c1b-1111-4222-8333-444455556666"
EV = "aaaaaaaa-0000-0000-0000-00000000f001"          # 합성 메시지 uuid
USER_TEXT = "이해 못한 건 승인하지 않고 설명 먼저 듣고 싶어.\n\n그리고 「추천대로」는 속도 때문에 쓴 비상수단이야."


def card_body(cid=CID, kind="대전제", proposer="agent", evid=None, counter="- 「추천대로」 132건은 반례처럼 보이지만 속도 압박의 비상수단이었다", extra=""):
    evid = evid if evid is not None else [f'- [msg:{EV[:8]}] "이해 못한 건 승인하지 않고 설명 먼저" (2026-11-06 17:39 KST · 세션 cfa72cfe)']
    return (f"---\nid: {cid}\ntitle: 이해 못 한 것은 승인하지 않는다\nkind: {kind}      # 대전제 | 습관 | …\nproposer: {proposer}\ntags: [불신, 피로]\n"
            f"implemented_via: 미정\nrelated: [nixos:11111111]\nlast_confirmed: 2026-11-06\n---\n## 내용\n이해하지 못한 제안은 승인하지 않고 설명을 먼저 요구한다.\n\n"
            f"## 근거 원문 (사용자 말만 — 한 건당 한 줄)\n" + "\n".join(evid) + f"\n\n## 반례·한계\n{counter}\n\n## 이력\n- 2026-11-06 · 만듦 · agent\n{extra}")


# ---------------------------------------------------------------- 파싱
meta, rest = cx.parse_frontmatter(card_body())
check("자체 머리말: 값·목록·줄 끝 설명(`  # …`)을 처리한다", meta["id"] == CID and meta["kind"] == "대전제" and meta["tags"] == ["불신", "피로"] and meta["related"] == ["nixos:11111111"], str(meta))
check("자체 머리말 없는 본문은 ({}, 본문 그대로)", cx.parse_frontmatter("## 내용\nx") == ({}, "## 내용\nx"))
card = cx.parse_card(card_body())
check("절을 이름 접두로 찾는다(`## 근거 원문 (설명…)` → 근거 원문)", set(card["sections"]) == {"내용", "근거 원문", "반례·한계", "이력"}, str(list(card["sections"])))
check("근거 한 줄 파싱: uuid·인용·메모", card["evidence"][0]["uuid"] == EV[:8] and card["evidence"][0]["quote"].startswith("이해 못한 건") and "17:39" in card["evidence"][0]["note"], str(card["evidence"]))
check("정상 카드는 검증 통과", cx.validate(card) == [], str(cx.validate(card)))

pe = cx.parse_evidence_line
check("근거 줄: 곡선 따옴표·낫표 인용", pe('- [msg:aabbccdd] “가나다” (메모)')["quote"] == "가나다" and pe("- [msg:aabbccdd] 「가나다」")["quote"] == "가나다")
q2 = pe('- [msg:aabbccdd] "그는 "맞다" 라고 했다" (메모)')
check("근거 줄: 인용 안에 같은 따옴표가 있어도 마지막 닫는 따옴표까지가 인용, 뒤는 메모", q2["quote"] == '그는 "맞다" 라고 했다' and q2["note"] == "(메모)", str(q2))
check("근거 줄: 포인터 표기", pe("- [msg:aabbccdd] (포인터 — 읽을 때 채움)")["pointer"] is True and pe("- [msg:aabbccdd] (포인터 — 읽을 때 채움)")["quote"] is None)
check("근거 줄: 인용·포인터 표기가 없으면 둘 다 거짓", pe("- [msg:aabbccdd]") == {"uuid": "aabbccdd", "quote": None, "pointer": False, "note": ""})
check("근거 줄 형식이 아니면 None(uuid 가 8자 미만·msg 없음)", pe("- [msg:abc] x") is None and pe("- 그냥 글") is None and pe("글") is None)

bad = cx.parse_card(card_body(kind="없는종류", proposer="robot", evid=["- 근거 아닌 글"], counter="").replace(f"id: {CID}", "id: 짧은id"))
pr = " / ".join(cx.validate(bad))
check("검증: 잘못된 kind·proposer·id·근거 줄·반례 없음을 각각 잡는다", all(k in pr for k in ("`kind`", "`proposer`", "uuid4", "근거 줄에", "반례")) , pr)
check("검증: 필수 칸 누락(title 비움)과 근거 0건", any("`title`" in x for x in cx.validate(cx.parse_card(card_body().replace("title: 이해 못 한 것은 승인하지 않는다", "title: ")))) and any("1건 이상" in x for x in cx.validate(cx.parse_card(card_body(evid=[])))))

# ---------------------------------------------------------------- 인용 일치
qm = cx.quote_matches
check("인용 일치: 공백·개행 정규화 뒤 부분 문자열", qm("설명 먼저 듣고", USER_TEXT) and qm("승인하지 않고   설명 먼저", USER_TEXT))
check("인용 일치: `…` 로 생략한 조각마다 검사", qm("이해 못한 건…추천대로", USER_TEXT) and not qm("이해 못한 건…전혀 다른 말", USER_TEXT))
check("인용 일치: 없는 말·빈 인용·너무 짧은 조각은 불일치", not qm("전혀 없는 문장입니다", USER_TEXT) and not qm("", USER_TEXT) and not qm("…", USER_TEXT))

FULL = {EV[:8]: ("ok", USER_TEXT, {"uuid": EV, "session": "cfa72cfe-x", "ts": None}), "bbbbbbbb": ("none",), "cccccccc": ("ambiguous", ["cccccccc-1", "cccccccc-2"])}
fetch = lambda pre: FULL.get(pre, ("none",))
c2 = cx.parse_card(card_body(evid=[f'- [msg:{EV[:8]}] "승인하지 않고 설명 먼저"', f'- [msg:{EV[:8]}] "지어낸 문장이다 정말로"', "- [msg:bbbbbbbb] \"없는 메시지\"", "- [msg:cccccccc] \"모호\"",
                                   f"- [msg:{EV[:8]}] (포인터 — 읽을 때 채움)", f"- [msg:{EV[:8]}]"]))
res = [x["status"] for x in cx.check_evidence(c2, fetch)]
check("근거 대조: 일치·미일치·메시지 없음·모호·포인터·인용 없음", res == ["일치", "미일치", "메시지 없음", "모호", "포인터", "인용 없음"], str(res))
check("근거 대조: 포인터·인용 없음은 전체 본문을 같이 돌려 읽는 쪽이 채운다", cx.check_evidence(c2, fetch)[4]["text"] == USER_TEXT)

# ---------------------------------------------------------------- 참조 해석
check("참조: `프로젝트:uuid8` 와 `uuid8`", cx.parse_ref("nixos:3F2A9C1B") == ("nixos", "3f2a9c1b") and cx.parse_ref("3f2a9c1b") == (None, "3f2a9c1b"))
for badref in ("nixos:3f2a", "nixos:zzzzzzzz", "", "nixos:"):
    try:
        cx.parse_ref(badref); ok = False
    except ValueError:
        ok = True
    check(f"참조: 8자 미만·16진 아님은 거부 — {badref!r}", ok)

# ---------------------------------------------------------------- 조회(여러 프로젝트) + 이력(git)
TMP = tempfile.mkdtemp(prefix="ctxcards-test-")
STORE = f"{TMP}/ctx"; os.makedirs(STORE)
open(f"{STORE}/manifest.toml", "w").write('[projects.alpha]\nrepo_url = "https://github.com/t/alpha"\nowner = "personal"\nremote = ""\n\n[projects.beta]\nrepo_url = "https://github.com/t/beta"\nowner = "personal"\nremote = ""\n\n[projects.gone]\nrepo_url = "https://github.com/t/gone"\nowner = "personal"\nremote = ""\n\n[projects.hub]\nrepo_url = "https://github.com/t/hub"\nowner = "personal"\nremote = "git@example.invalid:hub.git"\n')
GENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t", GIT_CONFIG_GLOBAL="/dev/null")


def git(proj, *a):
    return subprocess.run(["git", "-C", f"{STORE}/{proj}", *a], capture_output=True, text=True, env=GENV)


def put(proj, name, meta, body, msg):
    p = f"{STORE}/{proj}/note/{name}.md"; os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "w").write(st.render_header(meta) + body)
    git(proj, "add", "-A"); git(proj, "commit", "-q", "-m", msg)


for pj in ("alpha", "beta", "hub"):
    os.makedirs(f"{STORE}/{pj}"); git(pj, "init", "-q")
ID2 = "3f2affff-1111-4222-8333-444455556666"; ID3 = "9d9d9d9d-1111-4222-8333-444455556666"
put("alpha", f"cards/{CID}", {"state": "reviewed", "scope": "personal"}, card_body(), f"ctx: alpha/note/cards/{CID} (s1@h)")
put("alpha", f"cards/{CID}", {"state": "draft", "scope": "personal"}, card_body(extra="- 2026-11-06 · 에이전트 수정으로 강등 · agent\n"), f"ctx: alpha/note/cards/{CID} (s2@h)")
put("beta", f"cards/{ID2}", {"state": "draft", "scope": "project"}, card_body(cid=ID2), f"ctx: beta/note/cards/{ID2} (s3@h)")
put("beta", f"cards/{ID3}", {"state": "adopted", "scope": "project"}, card_body(cid=ID3), f"ctx: beta/note/cards/{ID3} (s3@h)")
put("beta", "cards/중첩/무시", {"state": "draft"}, card_body(), "ctx: beta/note/cards/중첩/무시 (s3@h)")
put("beta", "plan-not-card", {"state": "draft"}, "x\n", "ctx: beta/note/plan-not-card (s3@h)")

rows, skipped = cx.find_cards(STORE)
check("조회: 모든 프로젝트를 훑고(카드 3장) 저장소가 없는 프로젝트는 건너뛴 목록에", sorted(cx.ref_of(r) for r in rows) == sorted([f"alpha:{CID[:8]}", f"beta:{ID2[:8]}", f"beta:{ID3[:8]}"]) and skipped == ["gone"], str(([cx.ref_of(r) for r in rows], skipped)))
check("조회: `cards/` 바로 아래 문서만 카드(중첩·다른 이름 제외)", all("/" not in r["name"][len("cards/"):] and r["name"].startswith("cards/") for r in rows))
check("조회: uuid 앞자리 접두 — 앞 4자가 같은 두 카드는 8자로 가른다", [r["id"] for r in cx.find_cards(STORE, "3f2a9c1b")[0]] == [CID] and [r["id"] for r in cx.find_cards(STORE, "3f2affff")[0]] == [ID2])
check("조회: 프로젝트를 지정하면 그 프로젝트만(같은 접두라도 다른 프로젝트 카드는 안 나옴)", cx.find_cards(STORE, f"beta:{CID[:8]}")[0] == [])
IDX = CID[:8] + "-9999-4222-8333-000000000000"      # 앞 8자가 CID 와 같은 다른 프로젝트의 카드(uuid8 충돌)
put("beta", f"cards/{IDX}", {"state": "draft", "scope": "project"}, card_body(cid=IDX), f"ctx: beta/note/cards/{IDX} (s5@h)")
amb = cx.find_cards(STORE, CID[:8])[0]
check("조회: 프로젝트 없이 부른 uuid8 이 여러 프로젝트에 일치하면 모두 돌려준다(호출하는 쪽이 모호성 처리), `프로젝트:` 를 붙이면 하나", sorted(cx.ref_of(r) for r in amb) == sorted([f"alpha:{CID[:8]}", f"beta:{CID[:8]}"]) and len(cx.find_cards(STORE, f"alpha:{CID[:8]}")[0]) == 1)
try:
    cx.find_cards(STORE, "nope:3f2a9c1b"); ok = False
except ValueError as e:
    ok = "매니페스트에 없다" in str(e)
check("조회: 매니페스트에 없는 프로젝트는 오류", ok)
alpha = next(r for r in rows if r["project"] == "alpha")
check("조회: 저장소 머리말(state·scope)과 파싱된 카드·검증 결과를 함께", alpha["meta"]["state"] == "draft" and alpha["meta"]["scope"] == "personal" and alpha["card"]["meta"]["title"].startswith("이해 못 한") and alpha["problems"] == [])

hist = cx.history(STORE, "alpha", f"cards/{CID}")
check("이력: 최신이 위, `ctx: ` 접두를 뗀 제목, 판마다 state", [h["state"] for h in hist] == ["draft", "reviewed"] and hist[0]["subject"].startswith(f"alpha/note/cards/{CID}") and "(s2@h)" in hist[0]["subject"], str(hist))
check("이력: 강등(reviewed → draft)은 두 판의 state 비교로 표시, 첫 판은 강등 아님", hist[0]["demoted"] is True and hist[1]["demoted"] is False)
d = cx.revision_diff(STORE, "alpha", hist[0], hist[1])
check("이력: 판 diff 에 state 변경과 이력 줄 추가가 나옴", "-state: reviewed" in d and "+state: draft" in d and "에이전트 수정으로 강등" in d, d[:300])
check("이력: 첫 판의 diff 는 전체 추가", "+state: reviewed" in cx.revision_diff(STORE, "alpha", hist[1], None))
check("이력: 문서가 없으면 빈 목록(예외 없음)", cx.history(STORE, "alpha", "cards/없음") == [])


# ---------------------------------------------------------------- 쓰기 가드(순수 함수)
MAN = st.load_manifest(STORE)
hstate = lambda body, key="state": (st.split_header(body)[0] or {}).get(key)      # 머리말이 없으면 None(예외 없이 시험이 실패로 보고되게)
NOEV = lambda u8: (None, False)
def guard(body, cur=None, human=False, project="alpha", name=None, ev=NOEV):
    return cx.guard_proposal(body, cur, human=human, project=project, name=name or f"cards/{CID}", manifest=MAN, evidence_project=ev, session="abcdef12-0000", host="h9", today="2026-11-07")
cur_rev = {"meta": {**st.default_meta(), "state": "reviewed", "scope": "personal"}, "body": card_body()}
nb, er, wn = guard(card_body())
check("가드: 헤더 없는 새 카드는 state draft 헤더를 채워 돌려준다(저장소 기본값은 unknown)", er == [] and hstate(nb) == "draft" and st.split_header(nb)[1] == card_body(), str((er, nb[:60])))
check("가드: 새 카드가 state reviewed 를 주장하면 거부(에이전트 경로)", any("draft 여야" in e for e in guard(st.render_header({"state": "reviewed"}) + card_body())[1]))
check("가드: 새 카드가 state adopted 를 주장해도 거부", any("draft 여야" in e for e in guard(st.render_header({"state": "adopted"}) + card_body())[1]))
check("가드: proposer: user 는 거부(에이전트 경로)", any("proposer: user" in e for e in guard(card_body(proposer="user"))[1]))
check("가드: 사람(TTY)은 proposer: user · state reviewed 새 카드도 된다", guard(st.render_header({"state": "reviewed"}) + card_body(proposer="user"), human=True)[1] == [])
check("가드: draft → reviewed 로 올리는 제안은 거부(에이전트 경로)", any("올리는 제안" in e for e in guard(st.render_header({"state": "reviewed"}) + card_body(extra="- 변경\n"), cur={"meta": {**st.default_meta(), "state": "draft"}, "body": card_body()})[1]))
edited = card_body(extra="- 2026-11-07 · 내용 수정\n").replace("이해하지 못한 제안은", "이해하지 못한 제안과 긴급 수정은")
nb, er, wn = guard(edited, cur=cur_rev)
h2, t2 = st.split_header(nb)
check("가드: 확인된 카드(reviewed)의 내용을 고치면 draft 로 강등 — 헤더 없는 제안도(저장소가 기존 머리말을 물려주는 구멍)", er == [] and hstate(nb) == "draft" and hstate(nb, "scope") == "personal", str((er, h2)))
check("가드: 강등하면 last_confirmed 를 비우고 이력에 한 줄(날짜·사유·세션@호스트)", "last_confirmed:\n" in (t2 or "") and "- 2026-11-07 · 에이전트 수정으로 강등(reviewed → draft" in t2 and "abcdef12@h9" in t2 and any("강등했다" in w for w in wn), t2[-260:])
check("가드: 헤더에 reviewed 를 그대로 적은 수정 제안도 강등(상태 유지 주장은 무시)", hstate(guard(st.render_header({"state": "reviewed"}) + edited, cur=cur_rev)[0]) == "draft")
check("가드: 내용이 같은 재제안은 강등하지 않는다(헤더만 같음)", guard(card_body(), cur=cur_rev)[0] == card_body() and not guard(card_body(), cur=cur_rev)[2])
nb_h, er_h, _ = guard(edited, cur=cur_rev, human=True)
check("가드: 사람(TTY)이 고치면 강등하지 않는다(상태 유지·본문 그대로)", er_h == [] and nb_h == edited)
check("가드: adopted 도 수정하면 강등", hstate(guard(edited, cur={"meta": {**st.default_meta(), "state": "adopted"}, "body": card_body()})[0]) == "draft")
check("가드: 형식 문제(반례 없음)는 사람에게도 거부", any("반례" in e for e in guard(card_body(counter=""), human=True)[1]))
check("가드: id 가 문서 이름과 다르면 거부", any("다르다" in e for e in guard(card_body(), name="cards/" + ID2)[1]))
ev_map = {"bbbbbbbb": ("beta", True), "dddddddd": ("hub", True), "eeeeeeee": (None, True), "ffffffff": (None, False)}
def evp(u8):
    if u8 == "99999999":
        raise RuntimeError("DB 접속 실패")
    return ev_map[u8]
quote_card = lambda u8: card_body(evid=[f'- [msg:{u8}] "승인하지 않고 설명 먼저"'])
check("가드: remote 가 있는 저장소(hub)의 카드에 remote 없는 프로젝트(beta) 대화의 원문 인용은 거부하고 포인터를 안내", any("beta" in e and "포인터" in e for e in guard(quote_card("bbbbbbbb"), project="hub", ev=evp)[1]))
check("가드: 같은 메시지를 포인터로 적으면 통과", guard(card_body(evid=["- [msg:bbbbbbbb] (포인터 — 읽을 때 채움)"]), project="hub", ev=evp)[1] == [])
check("가드: remote 가 있는 프로젝트 자신의 대화 인용은 통과", guard(quote_card("dddddddd"), project="hub", ev=evp)[1] == [])
check("가드: remote 가 없는 저장소(alpha)의 카드는 어느 대화든 인용 가능", guard(quote_card("bbbbbbbb"), project="alpha", ev=evp)[1] == [])
_, er_u, wn_u = guard(quote_card("eeeeeeee"), project="hub", ev=evp)
check("가드: 세션의 프로젝트를 모르면 거부하지 않고 경고(오탐 방지)", er_u == [] and any("알 수 없어" in w for w in wn_u))
_, er_n, wn_n = guard(quote_card("ffffffff"), project="hub", ev=evp)
check("가드: 메시지를 DB 에서 못 찾으면 경고만", er_n == [] and any("찾지 못해" in w for w in wn_n))
check("가드: 출처 조회가 실패하면(DB 접속 등) remote 있는 저장소에서는 인용을 거부(fail-closed)", any("확인하지 못했다" in e for e in guard(quote_card("99999999"), project="hub", ev=evp)[1]))
check("가드: 출처 조회가 필요 없는 경우(포인터만)에는 조회를 부르지 않는다", guard(card_body(evid=["- [msg:99999999] (포인터 — 읽을 때 채움)"]), project="hub", ev=evp)[1] == [])
check("이력 줄 추가: 이력 절 끝(다음 절 앞)에 들어가고, 절이 없으면 새 절", cx.append_history("## 이력\n- a\n\n## 다음\nx\n", "- b") == "## 이력\n- a\n- b\n\n## 다음\nx\n" and cx.append_history("## 이력\n- a\n## 다음\nx\n", "- b") == "## 이력\n- a\n- b\n## 다음\nx\n")
check("이력 줄 추가: 이력 절이 없으면 끝에 새 절", cx.append_history("## 내용\nx\n", "- b").endswith("## 이력\n- b\n"))
check("카드 이름 판별: cards/<id> 만(중첩·접두만·다른 종류 제외)", cx.is_card_name("note", "cards/x") and not cx.is_card_name("note", "cards/") and not cx.is_card_name("note", "cards/a/b") and not cx.is_card_name("plan", "cards/x") and not cx.is_card_name("note", "other/x"))

# ---------------------------------------------------------------- 스킬(SKILL.md) — LLM 이 받는 입력이므로 코드와 어긋나지 않는지
SK = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(ROOT))), "_data", "claude-skills", "donghans-card", "SKILL.md")
sk = open(SK).read() if os.path.isfile(SK) else ""
check("스킬: SKILL.md 가 있고 머리말 name 이 폴더 이름과 같다", sk.startswith("---\nname: donghans-card\n") and "description:" in sk.split("---")[1])
check("스킬: 부르는 명령이 실제 명령과 같다(card show·card list·ctx msg·doc read·doc propose)", all(c in sk for c in ("donghans ctx card show", "donghans ctx card list", "donghans ctx msg", "donghans ctx doc read note cards/", "donghans ctx doc propose note cards/")))
check("스킬: 쟁점을 셸 명령에 넣지 않는다는 규칙과 카드 참조 형식(`프로젝트:uuid8`)이 있다", "쟁점은 셸 명령에 넣지 않는다" in sk and "프로젝트:uuid8" in sk)
check("스킬: 코드가 막는 규칙과 문구로만 안내하는 규칙을 구분해 적었다(어기면 아무도 모를 수 있다는 경고 포함)", "코드가 막는 것" in sk and "문구로만 안내하는 것" in sk and "아무도 모를 수 있" in sk)
check("스킬: 코드의 실제 가드와 같은 말을 한다 — proposer: user·reviewed 거부, 강등, 타 프로젝트 인용은 포인터", "proposer: user" in sk and "강등" in sk and "(포인터 — 읽을 때 채움)" in sk and "draft" in sk)
import re as _re
m_ = _re.search(r"```\n(---\nid:.*?)```", sk, _re.S)
tmpl = m_.group(1) if m_ else ""
tmpl = tmpl.replace("<uuid4 전체>", CID).replace("kind: 대전제 | 습관 | 한정 결정 | 희망사항 | 관점", "kind: 대전제").replace("[msg:<uuid8 이상>]", "[msg:aaaaaaaa]").replace("- …", "- 반례 하나")
tc = cx.parse_card(tmpl)
check("스킬: 안에 든 새 카드 템플릿이 실제 파서·검증을 통과한다(필수 칸·근거·반례)", cx.validate(tc) == [] and tc["meta"]["proposer"] == "agent" and tc["evidence"][0]["uuid"] == "aaaaaaaa", str((cx.validate(tc), tc["meta"])))
tok = _re.compile(r"^(?:[a-z0-9_]+:)?[0-9a-f]{8,36}$")
ok_refs = ("nixos:3f2a9c1b", "3f2a9c1b"); bad_refs = ("3f2a", "nixos:zzzz1234")
def _parses(r):
    try:
        cx.parse_ref(r); return True
    except ValueError:
        return False
check("스킬: 카드 참조 토큰 규칙(프로젝트:uuid8)이 ctxcards.parse_ref 와 같은 것을 받아들이고 같은 것을 거부한다", all(tok.match(x) and _parses(x) for x in ok_refs) and not any(tok.match(x) or _parses(x) for x in bad_refs))

# ---------------------------------------------------------------- CLI (임시 Postgres)
try:
    import psycopg  # noqa: F401
    import pgscratch
    pg = pgscratch.start()
except ImportError:
    pg = None
if not pg:
    print("psycopg/postgres 가 없어 CLI 시험을 건너뜀")
else:
    try:
        env = pg.env(CTX_STORE_DIR=STORE)
        import llm_ctx as cc
        os.environ.update(pg.env())
        conn = cc.connect()
        import ctx_secrets as csec
        csec.ensure_schema(conn); csec.add_secret(conn, "TESTPW", "literal", "hunter2-secret"); conn.commit()
        SID = "cfa72cfe-0000-0000-0000-000000000001"
        conn.execute("INSERT INTO sessions (session_id, host, hosts, repo_url, first_ts, last_ts) VALUES (%s,'h1','{h1}','https://github.com/t/alpha',now(),now())", (SID,))
        conn.execute("INSERT INTO messages (uuid, session_id, host, ts, role, kind, text, raw) VALUES (%s,%s,'h1',now(),'user','prompt',%s,%s)",
                     (EV, SID, USER_TEXT + " 비밀번호는 hunter2-secret 이야", json.dumps({"uuid": EV, "type": "user", "message": {"role": "user", "content": USER_TEXT + " 비밀번호는 hunter2-secret 이야"}})))
        conn.commit()

        def cli(*a):
            return subprocess.run([sys.executable, os.path.join(ROOT, "llm_ctx.py"), "ctx", "card", *a], capture_output=True, text=True, env={**env, "PYTHONPATH": ROOT}, timeout=60)
        # 합성 카드에 포인터·미일치 근거를 더한 문서
        ID4 = "77777777-1111-4222-8333-444455556666"
        put("alpha", f"cards/{ID4}", {"state": "draft", "scope": "personal"}, card_body(cid=ID4, evid=[f'- [msg:{EV[:8]}] "승인하지 않고 설명 먼저"', f'- [msg:{EV[:8]}] "지어낸 문장이다 정말로"', f"- [msg:{EV[:8]}] (포인터 — 읽을 때 채움)", "- [msg:bbbbbbbb] \"없는 메시지\""]), f"ctx: alpha/note/cards/{ID4} (s4@h)")
        r = cli("show", f"alpha:{ID4[:8]}")
        o = r.stdout
        check("card show: 종료 코드 0, 머리말 줄에 참조·종류·범위·상태·제안자·제목", r.returncode == 0 and f"# alpha:{ID4[:8]}  대전제 · personal · draft · 제안자 agent  — 이해 못 한" in o, r.stdout + r.stderr)
        check("card show: 근거 줄마다 일치/미일치/포인터/메시지 없음을 붙인다", "↳ 일치" in o and "↳ ⚠ 미일치" in o and "↳ 포인터" in o and "↳ ⚠ 메시지 없음" in o, o)
        check("card show: 포인터는 DB 의 전체 본문을 채워 보이고 등록된 비밀은 치환", "추천대로" in o and "hunter2-secret" not in o and "[protected]" in o, o)
        r = cli("show", f"alpha:{CID[:8]}", "--history")
        check("card show --history: 판 목록과 강등 표시", "## 판 이력" in r.stdout and "강등" in r.stdout and "reviewed" in r.stdout, r.stdout)
        r = cli("show", CID[:8])
        check("card show: 프로젝트 없이 부른 uuid8 이 두 프로젝트에 일치하면 후보 목록과 종료 코드 1", r.returncode == 1 and "2건" in r.stdout and f"alpha:{CID[:8]}" in r.stdout and f"beta:{CID[:8]}" in r.stdout and "프로젝트:uuid8" in r.stdout, r.stdout + r.stderr)
        r = cli("show", "3f2a")
        check("card show: 8자 미만 참조는 거부(종료 코드 1이 아니라 오류 메시지)", r.returncode != 0 and "uuid 앞 8자" in (r.stdout + r.stderr), r.stdout + r.stderr)
        r = cli("show", "zzzzzzzz:3f2a9c1b")
        check("card show: 매니페스트에 없는 프로젝트는 오류", r.returncode != 0 and "매니페스트에 없다" in (r.stdout + r.stderr))
        r = cli("show", "beelink:3f2a9c1b".replace("beelink", "gone"))
        check("card show: 이 머신에 저장소가 없는 프로젝트는 건너뜀 안내와 종료 코드 1", r.returncode == 1 and "gone" in r.stdout, r.stdout + r.stderr)
        r = cli("list")
        check("card list: 5장과 건너뛴 프로젝트 안내", r.returncode == 0 and f"alpha:{CID[:8]}" in r.stdout and "카드 5장" in r.stdout and "건너뛴 프로젝트: gone" in r.stdout, r.stdout)
        r = cli("list", "--state", "adopted")
        check("card list --state: 상태 필터", f"beta:{ID3[:8]}" in r.stdout and "카드 1장" in r.stdout and CID[:8] not in r.stdout, r.stdout)
        r = cli("list", "--project", "beta")
        check("card list --project: 그 프로젝트만", "alpha:" not in r.stdout and "카드 3장" in r.stdout, r.stdout)

        # ---- 쓰기 가드: 실제 `ctx doc propose` 프로세스(비-TTY = 에이전트 경로)와 가상 터미널(사람)
        VIEWS = f"{TMP}/views"
        genv = {**env, "PYTHONPATH": ROOT, "CTX_VIEWS_DIR": VIEWS, "CTX_SYNC_INLINE": "1", "CTX_PROPOSE_WAIT": "5"}
        for k in ("CLAUDECODE", "GEMINI_CLI", "DONGHANS_AGENT"):
            genv.pop(k, None)
        SES = "dddddddd-0000-0000-0000-00000000aaaa"

        def doc(*a, stdin=None):
            r = subprocess.run([sys.executable, os.path.join(ROOT, "llm_ctx.py"), "ctx", "doc", *a, "--project", "hub", "--session", SES], capture_output=True, text=True, input=stdin, env=genv, timeout=60)
            return r.returncode, r.stdout, r.stderr
        HID = "5a5a5a5a-1111-4222-8333-444455556666"
        rc, out, err = doc("propose", "note", f"cards/{HID}", "--stdin", stdin=card_body(cid=HID, evid=["- [msg:dddddddd] (포인터 — 읽을 때 채움)"]))
        txt = open(f"{STORE}/hub/note/cards/{HID}.md").read() if os.path.exists(f"{STORE}/hub/note/cards/{HID}.md") else ""
        check("가드 CLI: 헤더 없는 새 카드는 반영되고 파일에 state: draft 가 채워진다", rc == 0 and "state: draft" in txt and "draft 로 채웠다" in err, out + err + txt[:200])
        HID2 = "6b6b6b6b-1111-4222-8333-444455556666"
        rc, out, err = doc("propose", "note", f"cards/{HID2}", "--stdin", stdin=st.render_header({"state": "reviewed"}) + card_body(cid=HID2, evid=["- [msg:dddddddd] (포인터 — 읽을 때 채움)"]))
        check("가드 CLI: 새 카드가 reviewed 를 주장하면 거부(종료 코드 1, 파일 안 생김)", rc == 1 and "draft 여야" in err and not os.path.exists(f"{STORE}/hub/note/cards/{HID2}.md"), err)
        rc, out, err = doc("propose", "note", f"cards/{HID2}", "--stdin", stdin=card_body(cid=HID2, proposer="user", evid=["- [msg:dddddddd] (포인터 — 읽을 때 채움)"]))
        check("가드 CLI: proposer: user 는 거부", rc == 1 and "proposer: user" in err, err)
        rc, out, err = doc("propose", "note", f"cards/{HID2}", "--stdin", stdin=card_body(cid=HID2, counter="", evid=["- [msg:dddddddd] (포인터 — 읽을 때 채움)"]))
        check("가드 CLI: 반례 없는 카드는 거부", rc == 1 and "반례" in err, err)
        # 확인된 카드를 저장소에 직접 만들어 두고(사람이 llmui 로 올린 것을 흉내), 에이전트가 읽은 뒤 고친다
        RID = "7c7c7c7c-1111-4222-8333-444455556666"
        put("hub", f"cards/{RID}", {"state": "reviewed", "scope": "personal"}, card_body(cid=RID, evid=["- [msg:dddddddd] (포인터 — 읽을 때 채움)"]), f"ctx: hub/note/cards/{RID} (s0@h)")
        rc, out, err = doc("read", "note", f"cards/{RID}")
        fixed = card_body(cid=RID, evid=["- [msg:dddddddd] (포인터 — 읽을 때 채움)"]).replace("설명을 먼저 요구한다.", "설명을 먼저 요구한다(긴급 수정은 예외).")
        rc, out, err = doc("propose", "note", f"cards/{RID}", "--stdin", stdin=fixed)
        h3, t3 = st.split_header(open(f"{STORE}/hub/note/cards/{RID}.md").read())
        check("가드 CLI: 에이전트가 reviewed 카드를 고치면 반영은 되지만 draft 로 강등·last_confirmed 비움·이력 한 줄", rc == 0 and h3["state"] == "draft" and "last_confirmed:\n" in t3 and "에이전트 수정으로 강등(reviewed → draft" in t3 and "강등했다" in err, out + err + str(h3))
        hh = cx.history(STORE, "hub", f"cards/{RID}")
        check("가드 CLI: 강등이 판 이력에 보인다(두 판의 state 비교)", [h["demoted"] for h in hh] == [True, False], str([(h["short"], h["state"], h["demoted"]) for h in hh]))
        rc, out, err = doc("read", "note", f"cards/{RID}")
        rc, out, err = doc("propose", "note", f"cards/{RID}", "--stdin", stdin=st.render_header({"state": "adopted", "scope": "personal"}) + fixed.replace("(긴급 수정은 예외)", "(긴급 수정은 예외, 재수정)"))
        check("가드 CLI: draft 카드를 adopted 로 올리는 제안은 거부", rc == 1 and "올리는 제안" in err, err)
        # 타 프로젝트 인용: beta(remote 없음) 대화의 원문 인용은 hub(remote 있음) 카드에 못 쓴다
        SB, SH, SX = "bb000000-0000-0000-0000-00000000000b", "dd000000-0000-0000-0000-00000000000d", "ee000000-0000-0000-0000-00000000000e"
        for sid_, url in ((SB, "https://github.com/t/beta"), (SH, "https://github.com/t/hub"), (SX, "https://github.com/t/unknown")):
            conn.execute("INSERT INTO sessions (session_id, host, hosts, repo_url, first_ts, last_ts) VALUES (%s,'h1','{h1}',%s,now(),now())", (sid_, url))
        for u_, sid_ in (("bbbbbbbb-0000-0000-0000-00000000f002", SB), ("dddddddd-0000-0000-0000-00000000f003", SH), ("eeeeeeee-0000-0000-0000-00000000f004", SX)):
            conn.execute("INSERT INTO messages (uuid, session_id, host, ts, role, kind, text, raw) VALUES (%s,%s,'h1',now(),'user','prompt',%s,'{}')", (u_, sid_, USER_TEXT))
        conn.commit()
        QID = "8d8d8d8d-1111-4222-8333-444455556666"
        rc, out, err = doc("propose", "note", f"cards/{QID}", "--stdin", stdin=card_body(cid=QID, evid=['- [msg:bbbbbbbb] "승인하지 않고 설명 먼저"']))
        check("가드 CLI: hub(remote 있음) 카드에 beta(remote 없음) 대화의 원문 인용은 거부 — 포인터를 안내", rc == 1 and "beta" in err and "포인터" in err and not os.path.exists(f"{STORE}/hub/note/cards/{QID}.md"), err)
        rc, out, err = doc("propose", "note", f"cards/{QID}", "--stdin", stdin=card_body(cid=QID, evid=["- [msg:bbbbbbbb] (포인터 — 읽을 때 채움)"]))
        check("가드 CLI: 같은 메시지를 포인터로 적으면 반영", rc == 0 and os.path.exists(f"{STORE}/hub/note/cards/{QID}.md"), out + err)
        QID2 = "9e9e9e9e-1111-4222-8333-444455556666"
        rc, out, err = doc("propose", "note", f"cards/{QID2}", "--stdin", stdin=card_body(cid=QID2, evid=['- [msg:dddddddd] "승인하지 않고 설명 먼저"', '- [msg:eeeeeeee] "승인하지 않고 설명 먼저"']))
        check("가드 CLI: hub 자신의 대화 인용은 통과, 어느 프로젝트인지 모르는 세션은 경고만", rc == 0 and "알 수 없어" in err, out + err)
        # 사람(진짜 TTY): 같은 가드 중 사람 전용 허용(proposer: user · reviewed 새 카드)이 된다 — 에이전트 환경변수가 있으면 TTY 여도 거부
        import pty, select
        def run_pty(args, extra_env=None):
            e = {**genv, **(extra_env or {})}
            master, slave = pty.openpty()
            pr = subprocess.Popen([sys.executable, os.path.join(ROOT, "llm_ctx.py"), *args], stdin=slave, stdout=slave, stderr=slave, env=e, close_fds=True)
            os.close(slave); out_ = b""
            while True:
                r_, _, _ = select.select([master], [], [], 20)
                if not r_:
                    break
                try:
                    chunk = os.read(master, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                out_ += chunk
            pr.wait(timeout=20); os.close(master)
            return pr.returncode, out_.decode("utf-8", "replace")
        UID = "abababab-1111-4222-8333-444455556666"
        ufile = f"{TMP}/user-card.md"
        open(ufile, "w").write(st.render_header({"state": "reviewed", "scope": "personal"}) + card_body(cid=UID, proposer="user", evid=["- [msg:dddddddd] (포인터 — 읽을 때 채움)"]))
        rc, o = run_pty(["ctx", "doc", "propose", "note", f"cards/{UID}", "--file", ufile, "--project", "hub", "--session", SES])
        h4 = st.split_header(open(f"{STORE}/hub/note/cards/{UID}.md").read())[0] if os.path.exists(f"{STORE}/hub/note/cards/{UID}.md") else {}
        check("가드 CLI: 사람(TTY)은 proposer: user · state: reviewed 새 카드를 만들 수 있다", rc == 0 and h4.get("state") == "reviewed", o[-200:])
        UID2 = "bcbcbcbc-1111-4222-8333-444455556666"
        ufile2 = f"{TMP}/user-card2.md"
        open(ufile2, "w").write(st.render_header({"state": "reviewed"}) + card_body(cid=UID2, proposer="user", evid=["- [msg:dddddddd] (포인터 — 읽을 때 채움)"]))
        rc, o = run_pty(["ctx", "doc", "propose", "note", f"cards/{UID2}", "--file", ufile2, "--project", "hub", "--session", SES], {"CLAUDECODE": "1"})
        check("가드 CLI: 에이전트 표식(CLAUDECODE=1)이 있으면 TTY 여도 사람이 아니다 — 거부", rc == 1 and "proposer: user" in o and not os.path.exists(f"{STORE}/hub/note/cards/{UID2}.md"), o[-200:])
        conn.close()
    finally:
        pg.stop()
import shutil; shutil.rmtree(TMP, ignore_errors=True)
finish("ctxcards")
