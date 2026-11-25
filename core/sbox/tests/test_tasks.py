#!/usr/bin/env python3
"""sbox 작업 선언 시험(plan sbox-project-policy R6): 매니페스트 [tasks.*] → taskd 설정. 호스트 쪽 로직(승인·검증·재기록)을 지킨다.
 ① 승인 전(pinned 없음)에는 설정을 만들지 않는다 ② 승인 때와 다른 정의 파일은 거부 ③ --approve 는 현재 값을 pinned 로 매니페스트에 기록하고 다른 글자는 안 건드림
 ④ argv 는 문자열 목록(셸 문자열 거부)·이름·경로(절대·..)·kind 검증 ⑤ 승인한 뒤 다시 읽으면 설정이 만들어짐
실행: python3 -I core/sbox/tests/test_tasks.py  (mods/_tools/run-tests.sh 의 sbox-tasks)"""
import json, os, sys, tempfile, tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import tasks  # noqa: E402

n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


def expect_exit(label, fn, frag=""):
    try:
        fn(); check(label, False, "예외가 안 났다")
    except SystemExit as e:
        check(label, frag in str(e), str(e))


d = tempfile.mkdtemp(); mp = os.path.join(d, "m.toml")
base = '''# 손으로 쓴 주석은 승인 기록 뒤에도 남아야 한다
[project]
name = "p"
repo = "/x"

[network]
egress = ["a.example"]

[tasks.dev]
argv = ["npm", "run", "dev"]
cwd = "web"
kind = "service"
pins = ["web/package.json"]

[tasks.test]
argv = ["npm", "test"]
'''
open(mp, "w").write(base)
check("needed: 정의 파일 목록", tasks.needed(mp) == ["web/package.json"])
D = {"web/package.json": "a" * 64}
expect_exit("승인 전(pinned 없음)에는 설정을 만들지 않는다", lambda: tasks.build(mp, D, False), "승인되지 않았")
cfg, newpins = tasks.build(mp, D, True)
check("--approve 는 현재 값을 pins 로 담음", cfg["tasks"]["dev"]["pins"] == D and newpins == {"dev": D}, (cfg, newpins))
check("설정에 작업 사본 루트·종류·argv", cfg["root"] == "/home/sbox/work" and cfg["tasks"]["dev"]["kind"] == "service" and cfg["tasks"]["test"]["argv"] == ["npm", "test"])
tasks.set_pinned(mp, newpins)
text = open(mp).read(); data = tomllib.loads(text)
check("pinned 가 매니페스트에 기록됨(따옴표 키)", data["tasks"]["dev"]["pinned"] == D, data)
check("다른 글자(주석·[network])는 그대로", "손으로 쓴 주석" in text and data["network"] == {"egress": ["a.example"]} and data["tasks"]["test"]["argv"] == ["npm", "test"])
cfg2, _ = tasks.build(mp, D, False)
check("승인한 뒤 같은 값이면 --approve 없이 설정이 만들어짐", cfg2["tasks"]["dev"]["pins"] == D)
expect_exit("승인 때와 다른 정의 파일은 거부", lambda: tasks.build(mp, {"web/package.json": "b" * 64}, False), "승인 때와 다릅니다")
expect_exit("정의 파일을 ct 에서 못 읽으면 거부", lambda: tasks.build(mp, {}, False), "읽지 못했습니다")
tasks.set_pinned(mp, {"dev": {"web/package.json": "c" * 64}})
check("다시 승인하면 pinned 가 교체(중복 표 없음)", tomllib.loads(open(mp).read())["tasks"]["dev"]["pinned"] == {"web/package.json": "c" * 64} and open(mp).read().count("[tasks.dev.pinned]") == 1)
# 검증
def with_task(body):
    p = os.path.join(d, "v.toml"); open(p, "w").write("[tasks.x]\n" + body); return lambda: tasks.load(p)
expect_exit("argv 가 셸 문자열이면 거부", with_task('argv = "npm run dev"\n'), "목록")
expect_exit("argv 가 비면 거부", with_task("argv = []\n"), "목록")
expect_exit("argv 에 빈 문자열이 있으면 거부", with_task('argv = ["npm", ""]\n'), "목록")
expect_exit("kind 위반", with_task('argv = ["a"]\nkind = "daemon"\n'), "oneshot|service")
expect_exit("cwd 가 절대 경로면 거부", with_task('argv = ["a"]\ncwd = "/etc"\n'), "상대 경로")
expect_exit("cwd 에 .. 가 있으면 거부", with_task('argv = ["a"]\ncwd = "../.."\n'), "상대 경로")
expect_exit("pins 에 .. 가 있으면 거부", with_task('argv = ["a"]\npins = ["../x"]\n'), "상대 경로")
p = os.path.join(d, "bad.toml"); open(p, "w").write('[tasks."Bad Name"]\nargv = ["a"]\n')
expect_exit("작업 이름 형식 위반", lambda: tasks.load(p), "소문자")
print(f"sbox-tasks {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
