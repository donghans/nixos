#!/bin/sh
# 모든 도구의 자동 시험을 한 번에 실행한다. 사용: mods/_data/run-tests.sh   (실패한 묶음이 있으면 종료 코드 1)
# displayui(Textual) 시험은 textual 이 있는 파이썬이 필요: PYTHON=<그 python> 로 지정(없으면 설치된 displayui 가 쓰는 파이썬을 찾아 씀).
D=$(cd "$(dirname "$0")" && pwd); rc=0
for t in "vkb:vkb/tests/test_vkb.py" "vkb-cli:vkb/tests/test_vkb_cli.py" "posture:posture/tests/test_posture.py" "doctor:posture/tests/test_doctor.py" "touch-trace:touch-trace/tests/test_touch_trace.py"; do
  name=${t%%:*}; f=${t#*:}; out=$(cd "$D/$(dirname "$(dirname "$f")")" && timeout 300 python3 -I "tests/$(basename "$f")" 2>&1); r=$?
  printf '%-9s %s\n' "$name" "$(echo "$out" | tail -1)"; [ $r -eq 0 ] || { rc=1; echo "$out" | grep FAIL; }
done
PY=${PYTHON:-$(grep -o '/nix/store/[^ "]*python3[^ "]*/bin/python3[^ "]*' "$(command -v displayui 2>/dev/null)" 2>/dev/null | head -1)}
out=$(cd "$D/display" && PYTHON=${PY:-python3} sh tests/run.sh 2>&1); r=$?
printf '%-9s %s\n' display "$(echo "$out" | grep -E '코어|TUI' | tr '\n' ' ')"; [ $r -eq 0 ] || { rc=1; echo "$out" | grep -E "FAIL|Traceback"; }
find "$D" -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null
exit $rc
