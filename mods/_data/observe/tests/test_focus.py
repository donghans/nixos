#!/usr/bin/env python3
"""포커스/창 구간 시험: 상태 기계(이벤트 → 스팬), 제목 비기록, 소켓 읽기(가짜 서버), 종료 시 정리, observectl trace 와의 연결."""
import json, os, socket, sys, tempfile, threading, time
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
TMP = tempfile.mkdtemp(prefix="observe-focus-test-")
os.environ["OBSERVE_DATA_DIR"] = os.path.join(TMP, "var"); os.environ["OBSERVE_STATE_DIR"] = os.path.join(TMP, "state")
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
import observe_core as core, observe_events as oe, observe_focus as of, observe_trace as tr
from harness import checker
check, finish = checker()
os.makedirs(core.DATA_DIR, exist_ok=True)

rec = []
def emit(lvl, name, **kv):
    rec.append({"ev": name, **kv})
T = of.FocusTracker(emit, lookup=lambda a: "lookedup" if a == "abc999" else None)
T.handle("openwindow", "55a1,1,kitty,~/secret-dir 메일 제목, 쉼표 포함")
T.handle("activewindowv2", "55a1")
T.handle("openwindow", "55a2,2,vivaldi-stable,받은편지함 - 비밀 제목")
T.handle("activewindowv2", "55a2")
T.handle("activewindowv2", "")
T.handle("closewindow", "55a2")
names = [(r["ev"]) for r in rec]
check("열림→포커스→전환→해제→닫힘 순서의 이벤트", names == ["window:kitty.begin", "focus:kitty.begin", "window:vivaldi-stable.begin", "focus:kitty.end", "focus:vivaldi-stable.begin", "focus:vivaldi-stable.end", "window:vivaldi-stable.end"], str(names))
check("창 제목은 어떤 이벤트에도 기록되지 않음", "secret" not in json.dumps(rec) and "비밀" not in json.dumps(rec) and "메일" not in json.dumps(rec))
sp = {r["ev"]: r for r in rec}
check("포커스 스팬의 부모는 그 창 스팬, 같은 trace", sp["focus:kitty.begin"]["parent"] == sp["window:kitty.begin"]["span"] and sp["focus:kitty.begin"]["trace"] == sp["window:kitty.begin"]["trace"])
check("창 스팬은 루트(부모 없음), 속성 ws", sp["window:kitty.begin"]["parent"] is None and sp["window:kitty.begin"]["ws"] == "1")
check("같은 창에 활성 이벤트가 또 와도 새 스팬을 만들지 않음", (lambda n: (T.handle("activewindowv2", "55a1"), T.handle("activewindowv2", "55a1"), len([r for r in rec if r["ev"] == "focus:kitty.begin"]))[-1] == 2)(0))
rec.clear()
T.handle("activewindowv2", "0xABC999")
check("시작 전부터 있던 창: class 조회로 창 스팬을 먼저 열고 포커스(0x·대소문자 정규화)", [r["ev"] for r in rec] == ["focus:kitty.end", "window:lookedup.begin", "focus:lookedup.begin"], str([r["ev"] for r in rec]))
rec.clear()
T.handle("activewindowv2", "ffffff")
check("class 를 모르면 ? 로", "window:?.begin" in [r["ev"] for r in rec])
rec.clear()
T.close_all()
ends = [r["ev"] for r in rec]
check("close_all: 포커스·창 스팬을 전부 닫음(열린 스팬 없음)", ends[0].startswith("focus:") and all(e.endswith(".end") for e in ends) and not T.windows and T.focus is None, str(ends))
T2 = of.FocusTracker(emit)
rec.clear(); T2.handle("closewindow", "dead"); T2.handle("openwindow", "bad"); T2.handle("unknown", "x")
check("모르는 창 닫힘·깨진 열림·모르는 이벤트는 무시", rec == [])
check("class 정리: 특수문자·길이", of.clean_class("a b/c") == "a_b_c" and len(of.clean_class("x" * 100)) == 40 and of.clean_class("") == "?")

# --- 소켓: 가짜 Hyprland 가 이벤트를 보내고 닫으면 스팬이 로그에 남고 끝난다
path = os.path.join(TMP, ".socket2.sock")
srv = socket.socket(socket.AF_UNIX); srv.bind(path); srv.listen(1)
def serve():
    c, _ = srv.accept()
    for line in ("workspace>>1", "openwindow>>11,1,onlyoffice,문서 제목", "activewindowv2>>11", "windowtitlev2>>11,바뀐 제목", "activewindowv2>>", "activewindowv2>>11"):
        c.sendall((line + "\n").encode()); time.sleep(0.05)
    c.close()                                          # Hyprland 종료 → 열린 스팬 정리
th = threading.Thread(target=serve); th.start()
core.write_control({"components": {"*": "info"}})
of.run(path, events=oe.Events("windows"), do_snapshot=False)
th.join()
evs = list(core.iter_jsonl(core.state_dir(), "events"))
spans = {s["name"]: [x for x in tr.build_spans(evs) if x["name"] == s["name"]] for s in tr.build_spans(evs)}
check("소켓 경로: 창·포커스 스팬이 이벤트 로그에 기록", "window:onlyoffice" in spans and len(spans["focus:onlyoffice"]) == 2, str(list(spans)))
check("소켓이 닫히면 열려 있던 스팬도 끝남(running 없음)", all(s["status"] == "ok" for v in spans.values() for s in v))
check("제목(문서 제목·바뀐 제목)이 로그 어디에도 없음", "제목" not in json.dumps(evs, ensure_ascii=False))
check("observectl trace 의 트리: 창 아래 포커스 두 번", [(d, s["name"]) for d, s in tr.order_tree(tr.build_spans(evs))] == [(0, "window:onlyoffice"), (1, "focus:onlyoffice"), (1, "focus:onlyoffice")])
# --- 프로세스로 실행 + SIGTERM(서비스 중지): 열린 스팬을 닫고 끝나야 한다
import signal, subprocess
rt = os.path.join(TMP, "rt"); sig = "testsig"; os.makedirs(f"{rt}/hypr/{sig}")
path2 = f"{rt}/hypr/{sig}/.socket2.sock"
srv2 = socket.socket(socket.AF_UNIX); srv2.bind(path2); srv2.listen(1)
env = {**os.environ, "XDG_RUNTIME_DIR": rt, "HYPRLAND_INSTANCE_SIGNATURE": sig, "PATH": "/nonexistent"}   # hyprctl 없음 → 스냅샷은 건너뜀
pr = subprocess.Popen([sys.executable, os.path.join(ROOT, "observe_focus.py")], env=env)
c2, _ = srv2.accept()
c2.sendall(b"openwindow>>22,3,sigapp,x\nactivewindowv2>>22\n")
time.sleep(1.0)
pr.send_signal(signal.SIGTERM)
rc = pr.wait(timeout=10)
evs = list(core.iter_jsonl(core.state_dir(), "events"))
mine = [s for s in tr.build_spans(evs) if s["name"].endswith(":sigapp")]
check("SIGTERM: 정상 종료(0)하고 열린 창·포커스 스팬을 닫음", rc == 0 and len(mine) == 2 and all(s["status"] == "ok" for s in mine), f"rc={rc} {[(s['name'], s['status']) for s in mine]}")
finish("focus")
