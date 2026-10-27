import json, os, sys, time, random
R="/home/donghans/nixos/mods/_tools/claude-ctx"
sys.path.insert(0,R); sys.path.insert(0,R+"/tests")
import pgscratch
pg=pgscratch.start(); assert pg
os.environ.update(pg.env())
import claude_ctx as cc, ctx_secrets as cs
random.seed(3)
conn=cc.connect()
REPOS=["https://github.com/example/alpha","https://github.com/example/한글-프로젝트-매우긴저장소이름-테스트","https://github.com/example-org/beta-service","https://github.com/x/y"]
def add(sid,repo,host,msgs):
    conn.execute("INSERT INTO sessions (session_id, host, hosts, repo_url, first_ts, last_ts) VALUES (%s,%s,%s,%s,%s,%s)",(sid,host,[host],repo,msgs[0][2],msgs[-1][2]))
    for i,(role,kind,ts,text) in enumerate(msgs):
        conn.execute("INSERT INTO messages (uuid, session_id, host, ts, role, kind, text, raw) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",(f"{sid[:4]}-{i:04d}",sid,host,ts,role,kind,text,json.dumps({"i":i})))
LONG="긴 한글 문단입니다. 표와 박스가 깨지지 않는지 보기 위해 일부러 아주 길게 씁니다. English words are mixed in to check wrapping. "*6
CODE="def very_long_function_name(argument_one, argument_two, argument_three, argument_four, argument_five): return argument_one + argument_two\n"*3
big=[]
for i in range(160):
    role="user" if i%2==0 else "assistant"; kind="prompt" if role=="user" else "response"
    text=f"[{i}] "+(LONG if i%7==0 else CODE if i%11==0 else "짧은 메시지 "+str(i)+" 배포 일정 확인")
    big.append((role,kind,f"2026-10-20T{(i//60)+1:02d}:{i%60:02d}:00Z",text))
add("big00001",REPOS[0],"h1",big)
add("kor00001",REPOS[1],"h2",[("user","prompt","2026-10-21T01:00:00Z","한글 저장소 세션 배포 이야기"),("assistant","response","2026-10-21T01:00:10Z","알겠습니다")])
add("key00001",REPOS[2],"h1",[("user","prompt","2026-10-22T01:00:00Z","새 키는 sk-ant-api03-ZYXWVUTSRQPONMLKJIHGFEDCBA9876 이고 비밀번호는 Zq9!kd82Lm 이다 그리고 password=hunter99xyzQ"),("assistant","response","2026-10-22T01:00:10Z","받았다 hunter2-pass 로 설정")])
add("sho00001",REPOS[3],"h1",[("user","prompt","2026-10-23T01:00:00Z","짧은 세션")])
# 자동 메시지(스킬 호출·작업 알림·명령 출력) — 대화 화면의 배지·접기·제목 규칙 확인용
CMDX="<command-message>donghans-resume</command-message>\n<command-name>/donghans-resume</command-name>\n<command-args>c9bf7759-e82c-4c45-9ecf-026f384f601d</command-args>"
TASKX="<task-notification>\n<task-id>bnib4dcfr</task-id>\n<status>completed</status>\n<summary>Background command \"시험 보정 후 재실행\" completed (exit code 0)</summary>\n<output-file>/tmp/x/tasks/bnib4dcfr.output</output-file>\n</task-notification>"
add("aut00001",REPOS[0],"h1",[("user","prompt","2026-10-24T01:00:00Z",CMDX),("user","prompt","2026-10-24T01:01:00Z","ctxui 대시보드 만들어줘 끝났다"),("assistant","response","2026-10-24T01:01:20Z","알겠습니다 작업을 시작합니다"),
    ("user","prompt","2026-10-24T01:05:00Z",TASKX),("user","prompt","2026-10-24T01:06:00Z","<local-command-stdout>Compacted</local-command-stdout>"),("user","prompt","2026-10-24T01:07:00Z","<pasted_content>붙여넣은 로그 끝났다</pasted_content>"),("assistant","response","2026-10-24T01:07:30Z","확인했습니다 끝났다")])
add("bux00002",REPOS[3],"h1",[("user","prompt","2026-10-24T02:00:00Z",CMDX),("user","prompt","2026-10-24T02:01:00Z",TASKX)])
cs.add_secret(conn,"NAS_PW","literal","hunter2-pass",replace=True)
cs.add_secret(conn,"API_ENDPOINT_TOKEN","literal","tok_abcdefghij123456",replace=True)
for d in range(25):
    for k,(model,cost) in enumerate([("claude-sonnet-5-5",1.3+d*0.07),("claude-haiku-5-5",0.2+d*0.01),("claude-opus-5-5",2.1+d*0.1)]):
        conn.execute("INSERT INTO usage_events (request_id, host, ts, session_id, model, cost_usd, input_tokens, output_tokens, cache_read_tokens, cache_create_tokens) VALUES (%s,%s,%s,%s,%s,%s,1000,500,20000,300)",(f"g{d}-{k}","h1" if d%2 else "h2",f"2026-10-{(d%25)+1:02d}T0{k+1}:00:00Z","big00001",model,cost))
for n,(acct,email,plan,f,w) in enumerate([("A","a@x.test","max_5x",30,10),("A","a@x.test","max_5x",60,12),("B","b@x.test","pro",90,70)]):
    conn.execute("INSERT INTO limit_samples (host, ts, session_id, five_hour_pct, seven_day_pct, account_id, account_email, account_plan, five_hour_resets_at, seven_day_resets_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",("h1",f"2026-10-2{n}T01:00:00Z","big00001",f,w,acct,email,plan,"2026-10-27T01:00:00Z","2026-10-30T01:00:00Z"))
for repo,nm,body,host in [(REPOS[0],"instructions","# 알파 지침\n\n## QA 할 때\nqa 본문 "+LONG+"\n\n## 배포\n배포 본문\n","h1"),(REPOS[0],"override","알파 오버라이드\n","h2"),(REPOS[1],"instructions","한글 저장소 지침\n","h1")]:
    conn.execute("INSERT INTO project_instructions (repo_url, name, body, rev, updated_host) VALUES (%s,%s,%s,1,%s)",(repo,nm,body,host))
conn.commit() if hasattr(conn,"commit") else None
open(sys.argv[1],"w").write("\n".join(f"{k}={v}" for k,v in pg.env().items() if k.startswith("CLAUDE_CTX") or k=="HOME" or k.startswith("PG"))+"\n")
print("ready", flush=True)
time.sleep(900)
