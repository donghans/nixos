#!/usr/bin/env python3
"""key_probe 시험: 지정한 키만 이름별로 세고(눌림만), 나머지 키 이벤트는 개수로만 합산하며 내용은 기록하지 않는다."""
import os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "..", "_tools", "_lib", "testkit"))
import key_probe as kp
from harness import checker
check, finish = checker()

def ev(typ, code, val): return struct.pack(kp.FMT, 0, 0, typ, code, val)
watch = {14: "backspace", 106: "right"}
c = {"backspace": 0, "right": 0, "other_events": 0}
data = b"".join([ev(1, 14, 1), ev(1, 14, 0), ev(1, 14, 1), ev(1, 14, 2), ev(1, 14, 0),     # 백스페이스 2번 눌림(+뗌, 반복)
                 ev(1, 106, 1), ev(1, 106, 0),                                            # → 1번
                 ev(1, 30, 1), ev(1, 30, 0), ev(1, 48, 1),                                # a, b (watch 밖) 3개 이벤트
                 ev(0, 0, 0), ev(4, 4, 30)])                                              # SYN/MSC 는 무시
kp.count_events(data, watch, c)
check("백스페이스 눌림은 value=1 만 센다(뗌/반복 제외): 2", c["backspace"] == 2, str(c))
check("→ 눌림 1", c["right"] == 1, str(c))
check("watch 밖 키는 개수만(3개 이벤트), 어떤 키인지는 기록하지 않음", c["other_events"] == 3 and set(c) == {"backspace", "right", "other_events"}, str(c))
check("EV_KEY 가 아닌 이벤트(SYN, MSC)는 무시", True)
check("키 이름 → 코드 표에 방향키/백스페이스가 있음", kp.CODES["backspace"] == 14 and kp.CODES["left"] == 105 and kp.CODES["right"] == 106)
check("없는 장치 이름이면 None", kp.find_device("존재하지 않는 키보드") is None)
check("밝기 키 코드(224/225)가 표에 있음", kp.CODES["brightnessdown"] == 224 and kp.CODES["brightnessup"] == 225)
f = kp.find_devices(["존재하지 않는 키보드", "다른 없는 장치"])
check("없는 장치 이름 목록 → 모두 빈 목록", f == {"존재하지 않는 키보드": [], "다른 없는 장치": []}, str(f))
check("카운터 파일이 없으면 None", kp.read_counter("/nonexistent/gpe", "x") is None)
import tempfile
t = tempfile.NamedTemporaryFile("w", delete=False); t.write("  1234  other\n"); t.close()
check("gpe 파일 첫 숫자 읽기", kp.read_counter(t.name, "x") == 1234)
finish("key_probe")
