#!/usr/bin/env python3
"""ctx_secrets 시험(DB 없이): 치환 엔진 · 등록 검사 · 후보 탐지 · 주입 래퍼 · jsonl 파일 치환."""
import io, json, os, stat, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
import ctx_secrets as S
from harness import checker
check, finish = checker()
M = S.MASK

# --- 치환 엔진
secs = [dict(label="NAS_PW", kind="literal", value="hunter2-pass"), dict(label="SHORT", kind="literal", value="hunter2")]
m = S.Masker(secs)
check("literal 치환", m.text("pw=hunter2-pass 끝") == f"pw={M} 끝")
check("긴 값 먼저(부분 일치로 접미사가 남지 않음)", m.text("hunter2-pass") == M and "pass" not in m.text("hunter2-pass"))
check("짧은 값도 치환", m.text("a hunter2 b") == f"a {M} b")
check("여러 번 나와도 모두 치환", m.text("hunter2 hunter2-pass hunter2") == f"{M} {M} {M}")
check("비밀이 없으면 원문 그대로", m.text("아무 일 없음") == "아무 일 없음")
check("빈 문자열·None 통과", m.text("") == "" and m.text(None) is None)
q = S.Masker([dict(label="Q", kind="literal", value='a"b\\c한')])
check("JSON 이스케이프 형태도 치환(따옴표·역슬래시)", q.text('{"x":"a\\"b\\\\c한"}') == f'{{"x":"{M}"}}')
check("JSON \\uXXXX 형태도 치환", q.text('"a\\"b\\\\c\\ud55c"') == f'"{M}"')
check("obj(): dict·list·tuple 재귀", m.obj({"a": ["hunter2", ("x", "hunter2-pass")], "n": 3}) == {"a": [M, ("x", M)], "n": 3})
check("hits()", m.hits("hunter2") and not m.hits("hunter"))
check("labels_in(): 값 없이 이름만", m.labels_in("x hunter2-pass y") == ["NAS_PW", "SHORT"] or set(m.labels_in("x hunter2-pass y")) == {"NAS_PW", "SHORT"})
r = S.Masker([dict(label="TOK", kind="regex", value=r"tok_[a-z0-9]{6}")])
check("regex 치환", r.text("a tok_abc123 b tok_zzzzzz") == f"a {M} b {M}")
check("비어 있는 Masker 는 거짓", not S.Masker([]) and bool(m) and bool(r))
check("값에 정규식 특수문자가 있어도 literal 로 취급", S.Masker([dict(label="X", kind="literal", value="a.b*c(")]).text("a.b*c( axbbc(") == f"{M} axbbc(")

# --- 등록 검사
def bad(label, kind, value, force=False):
    try: S.validate(label, kind, value, force); return False
    except ValueError: return True
check("이름 규칙(영문 시작·영숫자_)", bad("1abc", "literal", "abcdef") and bad("a-b", "literal", "abcdef") and bad("", "literal", "abcdef") and not bad("A_b1", "literal", "abcdef"))
check("너무 짧은 값 거부, --force 면 허용", bad("A", "literal", "abc") and not bad("A", "literal", "abc", True))
check("빈 값 거부", bad("A", "literal", ""))
check("잘못된 정규식 거부", bad("A", "regex", "([a-"))
check("빈 문자열에 일치하는 정규식 거부(전부 지워 버림)", bad("A", "regex", "a*"))
check("정상 regex 허용", not bad("A", "regex", r"tok_[a-z]{6}"))
check("kind 검사", bad("A", "weird", "abcdef"))

# --- 미리보기·식별자
check("preview 는 전체 값을 포함하지 않음", "secretvalue123" not in S.preview("secretvalue123") and "(14자)" in S.preview("secretvalue123"))
check("fingerprint 는 안정적이고 값을 드러내지 않음", S.fingerprint("abc") == S.fingerprint("abc") and "abc" not in S.fingerprint("abc") and len(S.fingerprint("abc")) == 10)

# --- 후보 탐지(진짜 키처럼 보이는 가짜 값)
def names(t): return {n for n, v in S.find_candidates(t)}
def vals(t): return {v for n, v in S.find_candidates(t)}
check("OpenAI 형 키", "openai_key" in names("key sk-proj-abcDEF1234567890abcdEFGH end"))
check("Anthropic 키는 openai 와 안 겹침(한 번만)", [n for n, v in S.find_candidates("sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV")] == ["anthropic_key"])
check("GitHub 토큰", "github_token" in names("ghp_" + "a1B2c3D4e5" * 4))
check("AWS 액세스 키", "aws_access_key" in names("AKIAIOSFODNN7EXAMPLE"))
check("Slack 토큰", "slack_token" in names("xoxb-1234567890-abcdefghij"))
check("JWT", "jwt" in names("t eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"))
check("개인키 블록", "private_key_block" in names("-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"))
check("URL 안의 비밀번호만 값으로 잡음", vals("postgres://admin:S3cretPw!x@db.local:5432/x") == {"S3cretPw!x"})
check("password= 형태", "Zx9#kLm2$pQ" in vals("DB_PASSWORD=Zx9#kLm2$pQ"))
check('password: "…" 형태', "Tr0ub4dor&3x" in vals('password: "Tr0ub4dor&3x"'))
check("한국어 '비밀번호는 …'", "Qw3rty!9x" in vals("비밀번호는 Qw3rty!9x 입니다"))
check("자리표시자는 후보 아님", not vals("password=changeme") and not vals("token=<YOUR_TOKEN>") and not vals("password=${DB_PASSWORD}") and not vals("api_key=xxxxxxxx"))
check("이미 치환된 값은 후보 아님", not vals("password=[protected]") and not vals("비밀번호는 [protected] 입니다"))
check("평범한 한글 문장은 후보 아님", not vals("비밀번호를 입력하세요 라고 표시한다") and not vals("비밀번호는 교체해야합니다"))
check("한 종류 문자만(소문자만)이면 키워드형은 제외", not vals("password=abcdefghij"))
check("경로·코드 호출·코드 참조·snake_case 식별자는 키워드형 후보가 아님", not vals("password=/home/me/secret.txt") and not vals("password=~/.pw/file") and not vals("token=process.env.API_TOKEN")
      and not vals("password=getpass(prompt") and not vals("secret=my_secret_name") and not vals("token=$GITHUB_TOKEN") and not vals("password=https://x.y/z") and not vals("api_key=os.environ.get"))
check("경로가 아닌 진짜 비밀번호 모양은 유지(기호·숫자 포함)", {"hunter2-pass", "Tr0ub4dor&3x"} <= vals("password=hunter2-pass 그리고 token: Tr0ub4dor&3x"))

# --- 후보 집계
rows = [("s1", "https://x/a", None, "key sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV"), ("s2", "https://x/b", None, "again sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV"), ("s2", None, None, "")]
f = S.scan_messages(rows)
(fp, d), = f.items()
check("scan_messages: 같은 값은 한 후보로 합치고 횟수·세션·저장소를 센다", d["count"] == 2 and d["sessions"] == {"s1", "s2"} and d["repos"] == {"https://x/a", "https://x/b"} and d["pattern"] == "anthropic_key")
check("등록된 값은 후보에서 제외", not S.scan_messages(rows, S.Masker([dict(label="K", kind="literal", value="sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV")])))
check("무시한 값은 후보에서 제외", not S.scan_messages(rows, ignored={fp}))

# --- 주입 래퍼: 명령 만들기
reg = [dict(label="NAS_PW", kind="literal", value="hunter2-pass"), dict(label="PAT", kind="regex", value="tok_[a-z]{6}")]
argv, env, files = S.build_command(["curl", "-u", "me:{{secret:NAS_PW}}", "x"], reg)
check("{{secret:이름}} 을 값으로 치환, 환경변수는 요청한 것만", argv == ["curl", "-u", "me:hunter2-pass", "x"] and env == {})
argv, env, files = S.build_command(["echo"], reg, env_labels=["NAS_PW"])
check("env_labels 만 환경변수로", env == {"NAS_PW": "hunter2-pass"})
try:
    S.build_command(["x", "{{secret:NOPE}}"], reg); check("모르는 이름은 KeyError", False)
except KeyError as e:
    msg = str(e)
    check("모르는 이름은 KeyError 이고 값은 새지 않음", "NOPE" in msg and "NAS_PW" in msg and "hunter2-pass" not in msg)
try:
    S.build_command(["x", "{{secret:PAT}}"], reg); check("regex 는 주입 불가", False)
except KeyError:
    check("regex 등록은 주입 불가(literal 만)", True)
argv, env, files = S.build_command(["tool", "--pw-file", "{{secret-file:NAS_PW}}"], reg)
p = argv[2]
check("{{secret-file:이름}}: 0600 임시 파일에 값을 담음", os.path.isfile(p) and open(p).read() == "hunter2-pass" and stat.S_IMODE(os.stat(p).st_mode) == 0o600 and files == [p])
os.unlink(p)

# --- 주입 래퍼: 실제 실행(출력 치환·종료 코드)
out, err = io.StringIO(), io.StringIO()
rc = S.run_masked([sys.executable, "-c", "import sys; print('pw is', sys.argv[1]); print('e:', sys.argv[1], file=sys.stderr); sys.exit(3)", "{{secret:NAS_PW}}"], reg, out=out, err=err)
check("run_masked: 종료 코드 전달", rc == 3)
check("run_masked: 표준출력의 비밀이 [protected] 로", out.getvalue() == f"pw is {M}\n", repr(out.getvalue()))
check("run_masked: 표준오류도 치환", err.getvalue() == f"e: {M}\n", repr(err.getvalue()))
out, err = io.StringIO(), io.StringIO()
S.run_masked([sys.executable, "-c", "import os; print(os.environ.get('NAS_PW')); print('tok_abcdef')"], reg, env_labels=["NAS_PW"], out=out, err=err)
check("환경변수로 받은 값이 출력되어도, 등록된 regex 비밀도 치환", out.getvalue() == f"{M}\n{M}\n", repr(out.getvalue()))
out, err = io.StringIO(), io.StringIO()
rc = S.run_masked(["/nonexistent/cmd-xyz"], reg, out=out, err=err)
check("없는 명령은 127", rc == 127 and "찾을 수 없다" in err.getvalue())
tmpf = tempfile.mkdtemp()
os.environ["XDG_RUNTIME_DIR"] = tmpf
S.run_masked([sys.executable, "-c", "import sys; print(open(sys.argv[1]).read())", "{{secret-file:NAS_PW}}"], reg, out=io.StringIO(), err=io.StringIO())
check("secret-file 임시 파일은 실행 뒤 지워짐", not os.listdir(tmpf), str(os.listdir(tmpf)))

# --- 점검 캐시용 등록표 해시
r1 = S.registry_hash(secs)
check("registry_hash: 같은 등록표는 같고(순서 무관) 값이 바뀌면 달라지며 값을 담지 않음",
      r1 == S.registry_hash(list(reversed(secs))) and r1 != S.registry_hash([dict(secs[0], value="other-value"), secs[1]]) and "hunter" not in r1 and len(r1) == 16)

# --- jsonl 치환
def line(**kw): return json.dumps(kw, ensure_ascii=False).encode()
lines = [line(type="user", message={"content": "비번은 hunter2-pass 야"}), line(type="assistant", message={"content": "ok"}), b"", line(type="user", message={"content": 'quote a"b\\c한 end'})]
data = b"\n".join(lines) + b"\n"
secs2 = [dict(label="NAS_PW", kind="literal", value="hunter2-pass"), dict(label="Q", kind="literal", value='a"b\\c한')]
new, hits, skipped = S.scrub_bytes(data, secs2)
check("scrub_bytes: 치환되고 모든 줄이 여전히 JSON", all(json.loads(l) for l in new.split(b"\n") if l.strip()) and b"hunter2-pass" not in new and 'a"b\\c한'.encode() not in new and M.encode() in new)
check("scrub_bytes: JSON 이스케이프된 비밀도 치환(\\\" 와 \\\\)", b'a\\"b' not in new)
check("scrub_bytes: 비밀 없는 줄은 바이트 그대로", new.split(b"\n")[1] == lines[1] and new.split(b"\n")[2] == b"" and new.endswith(b"\n"))
check("scrub_bytes: 횟수 보고(값 없이 이름만)", hits == {"NAS_PW": 1, "Q": 1} and skipped == 0, str(hits))
check("scrub_bytes: 두 번 돌려도 같음(멱등)", S.scrub_bytes(new, secs2)[0] == new)
broken = b'{"a": "hunter2-pass", \n{"ok": "hunter2-pass"}\n'
nb, h2, sk2 = S.scrub_bytes(broken, [dict(label="NAS_PW", kind="literal", value="hunter2-pass")])
check("scrub_bytes: 원래 JSON 이 아니던 줄은 건드리지 않고 skipped", nb.split(b"\n")[0] == b'{"a": "hunter2-pass", ' and sk2 == 1 and b"hunter2-pass" not in nb.split(b"\n")[1])
check("scrub_bytes: 정규식 비밀도 줄 단위로 적용", S.scrub_bytes(line(t="x tok_abcdef y") + b"\n", [dict(label="PAT", kind="regex", value="tok_[a-z]{6}")])[0] == line(t=f"x {M} y") + b"\n")
check("scrub_bytes: 비밀이 없으면 입력과 동일", S.scrub_bytes(data, [])[0] == data)

finish("ctx_secrets")
