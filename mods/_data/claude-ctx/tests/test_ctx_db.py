#!/usr/bin/env python3
"""claude_ctx + ctx_secrets 통합 시험: 임시 Postgres(unix 소켓만)에 실제 schema.sql 을 올리고 적재·치환·주입·탐지·로컬 치환을 확인한다.
필요: psycopg 가 있는 python, postgres 17 바이너리(환경변수 CTX_PG_BIN 또는 /nix/store/*-postgresql-and-plugins-17*/bin). 없으면 건너뛴다(종료 코드 0)."""
import glob, json, os, re, shutil, subprocess, sys, tempfile, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
from harness import checker
check, finish = checker()
try:
    import psycopg  # noqa: F401
except ImportError:
    print("psycopg 가 없어 통합 시험을 건너뜀"); sys.exit(0)
PGBIN = os.environ.get("CTX_PG_BIN") or next(iter(sorted(glob.glob("/nix/store/*-postgresql-and-plugins-17*/bin"))), None) or ""
if not os.path.exists(os.path.join(PGBIN, "initdb")):
    print("postgres 바이너리를 못 찾아 통합 시험을 건너뜀(CTX_PG_BIN 지정)"); sys.exit(0)

TMP = tempfile.mkdtemp(prefix="ctxdb-test-"); PGDATA = os.path.join(TMP, "pg"); SOCK = os.path.join(TMP, "sock"); os.makedirs(SOCK)
HOME = os.path.join(TMP, "home"); os.makedirs(os.path.join(HOME, ".claude/projects/-tmp-proj"))
PORT = str(20000 + os.getpid() % 20000)
env = dict(os.environ, HOME=HOME, CLAUDE_CTX_HOST="testhost", CLAUDE_CTX_DSN=f"host={SOCK} port={PORT} dbname=claude_ctx user=claude_ctx", PYTHONDONTWRITEBYTECODE="1")
env.pop("CLAUDECODE", None)
os.environ.update(env)


def sh(*a, **k):
    return subprocess.run(a, capture_output=True, text=True, **k)


def stop():
    sh(os.path.join(PGBIN, "pg_ctl"), "-D", PGDATA, "-m", "immediate", "stop")
    shutil.rmtree(TMP, ignore_errors=True)


try:
    r = sh(os.path.join(PGBIN, "initdb"), "-D", PGDATA, "-U", "postgres", "--auth=trust", "-E", "UTF8", "--no-locale")
    assert r.returncode == 0, r.stderr
    r = sh(os.path.join(PGBIN, "pg_ctl"), "-D", PGDATA, "-w", "-o", f"-c listen_addresses= -c unix_socket_directories={SOCK} -c port={PORT} -c fsync=off", "-l", os.path.join(TMP, "pg.log"), "start")
    assert r.returncode == 0, r.stdout + r.stderr
    psql = lambda db, sql: sh(os.path.join(PGBIN, "psql"), "-h", SOCK, "-p", PORT, "-U", "postgres", "-d", db, "-v", "ON_ERROR_STOP=1", "-c", sql)
    assert psql("postgres", "CREATE ROLE claude_ctx LOGIN").returncode == 0
    assert psql("postgres", "CREATE DATABASE claude_ctx OWNER claude_ctx").returncode == 0
    r = sh(os.path.join(PGBIN, "psql"), "-h", SOCK, "-p", PORT, "-U", "postgres", "-d", "claude_ctx", "-v", "ON_ERROR_STOP=1", "-f", os.path.join(ROOT, "schema.sql"))
    check("schema.sql 이 그대로 적용됨(vector·pg_trgm 포함)", r.returncode == 0, r.stderr[-300:])

    sys.path.insert(0, ROOT)
    import ctx_secrets as cs
    import claude_ctx as cc
    schema_text = open(os.path.join(ROOT, "schema.sql")).read()
    check("schema.sql 이 ctx_secrets.SCHEMA_STATEMENTS 와 같은 DDL 을 담음", all(st in schema_text for st in cs.SCHEMA_STATEMENTS))

    SID = "11111111-aaaa-bbbb-cccc-000000000001"
    PW, KEY = "hunter2-pass", "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUV"
    tpath = os.path.join(HOME, ".claude/projects/-tmp-proj", SID + ".jsonl")
    def ln(i, role, text, ts):
        return json.dumps({"uuid": f"u{i:07d}-0000-0000-0000-000000000000", "sessionId": SID, "type": role, "timestamp": ts, "cwd": "/tmp/proj",
                           "message": {"role": role, "content": text}}, ensure_ascii=False)
    lines = [ln(1, "user", f"NAS 비번은 {PW} 이고 키는 {KEY} 야", "2026-10-01T01:00:00Z"), ln(2, "assistant", "알겠습니다. 기억하겠습니다.", "2026-10-01T01:00:05Z"),
             ln(3, "user", "DB_PASSWORD=Zx9#kLm2$pQ 로 접속해줘", "2026-10-01T01:01:00Z"), ln(4, "assistant", f"접속했습니다 ({PW} 사용)", "2026-10-01T01:01:05Z")]
    open(tpath, "w").write("\n".join(lines) + "\n")
    os.utime(tpath, (time.time() - 7200, time.time() - 7200))   # 2시간 전에 끝난 세션(한가함)
    conn = cc.connect()
    n = cc.ingest_transcript(conn, tpath); conn.commit()
    check("가짜 트랜스크립트 4줄 적재", n == 4, str(n))

    def cli(*a, stdin=None):
        return subprocess.run([sys.executable, os.path.join(ROOT, "claude_ctx.py"), *a], capture_output=True, text=True, env={**env, "PYTHONPATH": ROOT}, input=stdin, timeout=120)

    # --- 등록 전: 치환 없음
    r = cli("ctx", "search", "NAS")
    check("등록 전에는 그대로 보임(치환 대상 없음)", PW in r.stdout, r.stdout + r.stderr)

    # --- 등록(--stdin) · 목록
    r = cli("secret", "add", "NAS_PW", "--stdin", stdin=PW + "\n")
    check("secret add --stdin 성공, 값은 출력에 없음", r.returncode == 0 and PW not in r.stdout + r.stderr, r.stdout + r.stderr)
    r = cli("secret", "add", "NAS_PW", "--stdin", stdin="other-value\n")
    check("같은 이름 재등록은 거부(--replace 필요)", r.returncode != 0 and "이미 있다" in r.stderr + r.stdout)
    r = cli("secret", "add", "SHORT", "--stdin", stdin="ab\n")
    check("너무 짧은 값은 거부", r.returncode != 0 and "짧" in r.stderr + r.stdout)
    r = cli("secret", "add", "TOK", "--regex", "--stdin", stdin="tok_[a-z]{6}\n")
    check("regex 등록", r.returncode == 0)
    r = cli("secret", "list")
    check("list: 이름·길이·fp 만, 값은 없음", "NAS_PW" in r.stdout and "12자" in r.stdout and PW not in r.stdout and cs.fingerprint(PW) in r.stdout, r.stdout)
    r = cli("secret", "add", "NOTTY")
    check("TTY 가 아니면 값 직접 입력 등록 거부(--stdin 필요)", r.returncode != 0 and "터미널" in r.stderr + r.stdout)

    # --- 출력 치환
    r = cli("ctx", "search", "NAS")
    check("search: 비밀이 [protected]", PW not in r.stdout and "[protected]" in r.stdout, r.stdout)
    r = cli("ctx", "search", PW)
    check("search: 검색어에 비밀이 있으면 거부(존재 여부 노출 방지)", r.returncode != 0 and PW not in r.stdout + r.stderr and "비밀" in r.stderr + r.stdout)
    r = cli("ctx", "session", SID[:8])
    check("session: 치환됨, 비밀 없는 줄은 그대로", PW not in r.stdout and "[protected]" in r.stdout and "알겠습니다. 기억하겠습니다." in r.stdout, r.stdout)
    r = cli("ctx", "recent")
    check("recent: 첫 프롬프트 치환", PW not in r.stdout and "[protected]" in r.stdout, r.stdout)
    r = cli("ctx", "sql", "select text from messages order by ts")
    check("sql: 셀 치환", PW not in r.stdout and "[protected]" in r.stdout, r.stdout)
    r = cli("ctx", "sql", "select raw::text from messages order by ts")
    check("sql: jsonb 원본 셀도 치환", PW not in r.stdout and "[protected]" in r.stdout, r.stdout[:300])
    r = cli("ctx", "sql", "select value from secrets")
    check("sql: 등록표 직접 조회는 사람만(비 TTY 거부)", r.returncode != 0 and PW not in r.stdout + r.stderr)
    r = cli("ctx", "sql", "select * from SECRETS")
    check("sql: 대소문자 바꿔도 거부", r.returncode != 0 and PW not in r.stdout + r.stderr)
    for q in ('select value from public.secrets', 'select * from "secrets"', 'select 1 from messages, secrets', 'select (select value from secrets limit 1)', 'select * from secret_ignores'):
        r = cli("ctx", "sql", q)
        check(f"sql: 등록표 참조 형태 거부 — {q}", r.returncode != 0 and PW not in r.stdout + r.stderr, r.stdout + r.stderr)
    r = cli("ctx", "sql", "select count(*) from messages where text ilike '%secret%'")
    check("sql: 'secret' 이라는 단어를 찾는 정상 쿼리는 허용", r.returncode == 0, r.stdout + r.stderr)
    r = cli("ctx", "search", "NAS", "--raw")
    check("--raw 는 TTY 가 아니면 거부(Claude 가 풀 수 없음)", r.returncode != 0 and PW not in r.stdout, r.stdout + r.stderr)
    r = subprocess.run([sys.executable, os.path.join(ROOT, "claude_ctx.py"), "ctx", "search", "NAS", "--raw"], capture_output=True, text=True, env={**env, "PYTHONPATH": ROOT, "CLAUDECODE": "1"})
    check("CLAUDECODE 환경에서도 --raw 거부", r.returncode != 0 and PW not in r.stdout)
    r = cli("secret", "show", "NAS_PW")
    check("secret show 는 사람(TTY)만", r.returncode != 0 and PW not in r.stdout + r.stderr)

    # --- 사람(진짜 TTY)은 되고, 에이전트 표식이 있으면 TTY 여도 거부된다(가상 터미널로 확인)
    import pty, select
    def run_pty(args, extra_env=None):
        e = {k: v for k, v in env.items() if k not in ("CLAUDECODE", "GEMINI_CLI", "DONGHANS_AGENT")}
        e.update({"PYTHONPATH": ROOT, **(extra_env or {})})
        master, slave = pty.openpty()
        p = subprocess.Popen([sys.executable, os.path.join(ROOT, "claude_ctx.py"), *args], stdin=slave, stdout=slave, stderr=slave, env=e, close_fds=True)
        os.close(slave)
        out = b""
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
            out += chunk
        p.wait(timeout=20); os.close(master)
        return p.returncode, out.decode("utf-8", "replace")
    rc, o = run_pty(["secret", "show", "NAS_PW"])
    check("사람(진짜 TTY, 에이전트 표식 없음): secret show 가 값을 보여 줌", rc == 0 and PW in o, o[:120])
    rc, o = run_pty(["ctx", "search", "NAS", "--raw"])
    check("사람(TTY): --raw 로 치환이 풀려 원문이 보임", rc == 0 and PW in o and "[protected]" not in o, o[:160])
    for marker in ("CLAUDECODE", "GEMINI_CLI", "DONGHANS_AGENT"):
        rc, o = run_pty(["secret", "show", "NAS_PW"], {marker: "1"})
        check(f"에이전트 표식 {marker}=1 이면 TTY 여도 거부", rc != 0 and PW not in o and "사람이" in o, o[:140])
    rc, o = run_pty(["ctx", "search", "NAS"])
    check("TTY 에서도 기본(--raw 없음)은 치환된다", rc == 0 and PW not in o and "[protected]" in o)

    # 치환 후 자름: 스니펫 경계에서 비밀이 잘려도 조각이 남지 않음
    long = "가" * 55 + PW + "나" * 400
    conn.execute("INSERT INTO messages (uuid, session_id, host, ts, role, kind, text, raw) VALUES (%s,%s,'testhost',now(),'user','prompt',%s,'{}')", ("u9999999-0000-0000-0000-000000000000", SID, long)); conn.commit()
    r = cli("ctx", "search", "가가가")
    check("search: 경계에서 자르기 전에 치환(비밀 조각 없음)", "hunter" not in r.stdout and "pass" not in r.stdout.replace("[protected]", ""), r.stdout[-300:])

    # --- 주입 래퍼
    r = cli("secret", "run", "--", sys.executable, "-c", "import sys; print('pw=' + sys.argv[1]); print('tok_abcdef')", "{{secret:NAS_PW}}")
    check("secret run: 값은 인자로 들어가고 출력은 치환", r.returncode == 0 and r.stdout == "pw=[protected]\n[protected]\n", repr(r.stdout + r.stderr))
    r = cli("secret", "run", "--env", "NAS_PW", "--", sys.executable, "-c", "import os; print(os.environ['NAS_PW'])")
    check("secret run --env: 환경변수로 주고 출력 치환", r.stdout == "[protected]\n", r.stdout + r.stderr)
    r = cli("secret", "run", "--", "echo", "{{secret:NOPE}}")
    check("secret run: 모르는 이름은 실패하고 값이 새지 않음", r.returncode != 0 and "NOPE" in r.stderr and PW not in r.stdout + r.stderr)
    r = cli("secret", "run", "--", sys.executable, "-c", "import sys; sys.exit(7)")
    check("secret run: 종료 코드 전달", r.returncode == 7)
    r = cli("secret", "disable", "NAS_PW")
    r2 = cli("ctx", "search", "NAS")
    check("disable 하면 치환 해제(등록은 유지)", PW in r2.stdout)
    cli("secret", "enable", "NAS_PW")

    # --- 후보 탐지
    r = cli("secret", "scan")
    check("scan: 키·DB_PASSWORD 후보를 흐린 미리보기로 보임(값 없음)", "anthropic_key" in r.stdout and "assigned_secret" in r.stdout and KEY not in r.stdout and "Zx9#kLm2$pQ" not in r.stdout, r.stdout)
    check("scan: 이미 등록된 NAS 비번은 후보에서 제외", cs.fingerprint(PW) not in r.stdout)
    fp_key = cs.fingerprint(KEY)
    check("scan: 후보 식별자(fp) 표시", fp_key in r.stdout)
    r = cli("secret", "adopt", fp_key, "ANTHROPIC_KEY")
    check("adopt: 승인하면 등록, 값은 출력에 없음", r.returncode == 0 and KEY not in r.stdout + r.stderr, r.stdout + r.stderr)
    r = cli("ctx", "session", SID[:8])
    check("adopt 한 키도 이후 출력에서 치환", KEY not in r.stdout)
    r = cli("secret", "scan")
    check("adopt 한 후보는 목록에서 사라짐", fp_key not in r.stdout)
    fp_pw2 = cs.fingerprint("Zx9#kLm2$pQ")
    r = cli("secret", "ignore", fp_pw2)
    r = cli("secret", "scan")
    check("ignore 한 후보는 목록에서 사라짐", fp_pw2 not in r.stdout and "새 후보가 없다" in r.stdout, r.stdout)
    r = cli("secret", "ignore", fp_pw2, "--undo"); r = cli("secret", "scan")
    check("ignore --undo 로 되살림", fp_pw2 in r.stdout)
    r = cli("secret", "adopt", "deadbeef00", "X")
    check("없는 fp 는 실패", r.returncode != 0)

    # --- 로컬 치환(scrub)
    before = open(tpath, "rb").read()
    r = cli("secret", "scrub")
    check("scrub dry-run: 파일을 바꾸지 않음", open(tpath, "rb").read() == before and "dry-run" in r.stdout and "NAS_PW" in r.stdout and PW not in r.stdout, r.stdout)
    r = cli("secret", "scrub", "--apply", "--idle-min", "100000")
    check("scrub: 최근 수정 파일은 진행 중으로 보고 건너뜀", open(tpath, "rb").read() == before and "진행 중" in r.stdout, r.stdout)
    r = cli("secret", "scrub", "--apply")
    after = open(tpath, "rb").read()
    check("scrub --apply: 로컬 파일에서 비밀이 사라지고 [protected]", PW.encode() not in after and KEY.encode() not in after and b"[protected]" in after, r.stdout)
    check("scrub: 모든 줄이 여전히 JSON", all(json.loads(l) for l in after.decode().splitlines() if l.strip()))
    check("scrub: 수정 시각 보존(--days 선별에 영향 없음)", abs(os.path.getmtime(tpath) - (time.time() - 7200)) < 60)
    off = conn.execute("SELECT byte_offset FROM ingest_state WHERE host=%s AND path=%s", (cc.INGEST_HOST, tpath)).fetchone()[0]; conn.commit()
    check("scrub: ingest_state 오프셋이 새 파일 크기로 갱신", off == len(after), f"{off} vs {len(after)}")
    row = conn.execute("SELECT text FROM messages WHERE uuid='u0000001-0000-0000-0000-000000000000'").fetchone(); conn.commit()
    check("scrub 해도 DB 원문은 그대로 보존", PW in row[0] and KEY in row[0])
    check("scrub 후 같은 파일 재적재는 새 메시지 0건(중복·깨짐 없음)", cc.ingest_transcript(conn, tpath) == 0); conn.commit()
    with open(tpath, "a") as f:
        f.write(ln(5, "user", "새 줄", "2026-10-01T02:00:00Z") + "\n")
    check("scrub 후 새로 붙은 줄도 정상 적재(오프셋이 줄 경계에 맞음)", cc.ingest_transcript(conn, tpath) == 1); conn.commit()
    r = cli("secret", "scrub")
    check("scrub 두 번째 실행: 치환할 것 없음", "비밀 포함 0개" in r.stdout, r.stdout)
    r = cli("secret", "scrub")
    check("scrub 캐시: 바뀌지 않은 파일은 다시 읽지 않음(점검 생략)", "점검 생략 1" in r.stdout, r.stdout)
    r = cli("secret", "scrub", "--apply", "--quiet")
    check("scrub --quiet: 바꾼 것이 없으면 아무것도 출력하지 않음", r.returncode == 0 and r.stdout == "" and r.stderr == "", repr(r.stdout + r.stderr))
    cli("secret", "add", "LATE", "--stdin", stdin="기억하겠습니다\n")
    r = cli("secret", "scrub", "--apply", "--quiet")
    check("방금 수정된 파일은 진행 중으로 보고 건너뜀(--quiet 는 출력 없음)", r.stdout == "", repr(r.stdout))
    r = cli("secret", "scrub", "--apply", "--quiet", "--idle-min", "0")
    check("등록표가 바뀌면 캐시가 무효 — 새 비밀로 다시 점검해 치환(--quiet 도 바뀐 것은 보고)", "치환 1" in r.stdout and "기억하겠습니다" not in open(tpath).read(), r.stdout)
    check("scrub --no-cache 도 동작", cli("secret", "scrub", "--no-cache").returncode == 0)

    # --- 한도 샘플: 계정·리셋 시각 적재와 계정별 창별 최고값(ctx limits)
    od = os.path.join(HOME, ".local/share/claude-otel"); os.makedirs(od, exist_ok=True)
    def lim(ts, acct, f, w, fr=1792771800, wr=1793282400):
        return json.dumps({"ts": ts, "session_id": f"s-{acct}-{f}", "five_hour": {"used_percentage": f, "resets_at": fr}, "seven_day": {"used_percentage": w, "resets_at": wr},
                           "cost_usd": 1.0, "model": "m", "context_used_pct": 5, "account_id": acct, "account_email": f"{acct}@x.test" if acct else None})
    now = time.strftime("%Y-%m-%dT%H:%M:%S+0000", time.gmtime())
    open(os.path.join(od, "limits.jsonl"), "w").write("\n".join([lim(now, "A", 10, 20), lim(now, "A", 40, 25),
                                                              lim(now, "B", 70, 80), lim(now, None, 5, 6)]) + "\n")
    cc.ingest_otel(conn); conn.commit()
    rows = dict(conn.execute("SELECT coalesce(account_id,'?'), max(five_hour_pct) FROM limit_samples GROUP BY 1").fetchall())
    check("한도 샘플에 계정이 적재되고 계정별로 갈린다", rows.get("A") == 40 and rows.get("B") == 70 and rows.get("?") == 5, str(rows))
    check("리셋 시각이 timestamptz 로 적재", conn.execute("SELECT count(*) FROM limit_samples WHERE five_hour_resets_at IS NOT NULL AND seven_day_resets_at IS NOT NULL").fetchone()[0] == 4)
    r = cli("ctx", "limits", "--days", "3650")
    check("ctx limits: 계정별 5h 창 최고값 출력", "A@x.test" in r.stdout and "40.0%" in r.stdout and "B@x.test" in r.stdout and "70.0%" in r.stdout, r.stdout + r.stderr)

    # --- 표가 없는 옛 DB 에서도 조회 명령은 동작(마이그레이션 전 호환)
    conn.execute("DROP TABLE secrets"); conn.execute("DROP TABLE secret_ignores"); conn.commit()
    r = cli("ctx", "session", SID[:8])
    check("secrets 표가 없어도 조회는 동작(치환 없음)", r.returncode == 0, r.stderr)
    r = cli("secret", "list")
    check("표가 없으면 list 는 빈 안내", "등록된 비밀이 없다" in r.stdout, r.stdout + r.stderr)
    conn.close()
except AssertionError as e:
    check("준비 단계", False, str(e)[-400:])
finally:
    stop()
finish("ctx db")
