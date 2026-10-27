#!/bin/sh
# 모든 도구의 자동 시험을 한 번에 실행한다. 사용: mods/_tools/run-tests.sh   (실패한 묶음이 있으면 종료 코드 1)
# displayui(Textual) 시험은 textual 이 있는 파이썬이 필요: PYTHON=<그 python> 로 지정(없으면 설치된 displayui 가 쓰는 파이썬을 찾아 씀).
D=$(cd "$(dirname "$0")" && pwd); rc=0
for t in "ctx-secrets:llm-ctx/tests/test_secrets.py" "vkb:vkb/tests/test_vkb.py" "vkb-cli:vkb/tests/test_vkb_cli.py" "extkbd:extkbd/tests/test_extkbd.py" "posture:posture/tests/test_posture.py" "doctor:posture/tests/test_doctor.py" "touch-trace:touch-trace/tests/test_touch_trace.py" "notif:notif/tests/test_notif.py" "power-ab:power-ab/tests/test_power_ab.py" "devwatch:notif/tests/test_devwatch.py" "key_probe:input-debug/tests/test_key_probe.py" "observe:observe/tests/test_observe.py" "trace:observe/tests/test_trace.py" "bpf:observe/tests/test_bpf.py" "focus:observe/tests/test_focus.py" "abab:observe/tests/test_abab_lib.py" "netdata:observe/tests/test_netdata.py" "explain:observe/tests/test_explain.py" "tiers:observe/tests/test_tiers.py" "apps:observe/tests/test_apps.py" "query:observe/tests/test_query.py" "browser:observe/tests/test_browser.py" "usagegraph:observe/tests/test_usagegraph.py" "procctl:procui/tests/test_procctl.py" "diskbench:observe/tests/test_diskbench.py"; do
  name=${t%%:*}; f=${t#*:}; out=$(cd "$D/$(dirname "$(dirname "$f")")" && timeout 300 python3 -I "tests/$(basename "$f")" 2>&1); r=$?
  printf '%-9s %s\n' "$name" "$(echo "$out" | tail -1)"; [ $r -eq 0 ] || { rc=1; echo "$out" | grep FAIL; }
done
PY=${PYTHON:-$(grep -o '/nix/store/[^ "]*python3[^ "]*/bin/python3[^ "]*' "$(command -v displayui 2>/dev/null)" 2>/dev/null | head -1)}
# notif 는 위에서 (textual 없이) 핵심만 돌렸고, 화면 시험은 textual 이 있는 python 으로 한 번 더
[ -n "$PY" ] && { out=$(cd "$D/notif" && PYTHONDONTWRITEBYTECODE=1 timeout 300 "$PY" tests/test_notif.py 2>&1); r=$?; printf '%-9s %s\n' notif-ui "$(echo "$out" | tail -1)"; [ $r -eq 0 ] || { rc=1; echo "$out" | grep FAIL; }; }
[ -n "$PY" ] && { out=$(cd "$D/observe" && PYTHONDONTWRITEBYTECODE=1 timeout 300 "$PY" tests/test_usagefleet.py 2>&1); r=$?; printf '%-9s %s\n' usagefleet "$(echo "$out" | tail -1)"; [ $r -eq 0 ] || { rc=1; echo "$out" | grep FAIL; }; }
[ -n "$PY" ] && { out=$(cd "$D/observe" && PYTHONDONTWRITEBYTECODE=1 timeout 300 "$PY" tests/test_usage.py 2>&1); r=$?; printf '%-9s %s\n' usageui "$(echo "$out" | tail -1)"; [ $r -eq 0 ] || { rc=1; echo "$out" | grep FAIL; }; }
[ -n "$PY" ] && { out=$(cd "$D/clipboard" && PYTHONDONTWRITEBYTECODE=1 timeout 300 "$PY" -I tests/test_clipui.py 2>&1); r=$?; printf '%-9s %s\n' clipui "$(echo "$out" | tail -1)"; [ $r -eq 0 ] || { rc=1; echo "$out" | grep FAIL; }; }
[ -n "$PY" ] && { out=$(cd "$D/_lib/_uikit" && PYTHONDONTWRITEBYTECODE=1 timeout 300 "$PY" tests/test_uikit.py 2>&1); r=$?; printf '%-9s %s\n' uikit "$(echo "$out" | tail -1)"; [ $r -eq 0 ] || { rc=1; echo "$out" | grep FAIL; }; }
out=$(cd "$D/display" && PYTHON=${PY:-python3} sh tests/run.sh 2>&1); r=$?
printf '%-9s %s\n' display "$(echo "$out" | grep -E '코어|TUI' | tr '\n' ' ')"; [ $r -eq 0 ] || { rc=1; echo "$out" | grep -E "FAIL|Traceback"; }
# ctx(DB 통합·화면): psycopg + textual 이 모두 있는 python 이 필요하다 — CTX_PYTHON 으로 지정하거나(없으면 nix 로 한 번 만든다), postgres 17 이 없으면 시험 파일이 알아서 건너뛴다.
CTXPY=${CTX_PYTHON:-$(nix build --no-link --print-out-paths --impure --expr '(builtins.getFlake "nixpkgs").legacyPackages.x86_64-linux.python3.withPackages (ps: [ps.psycopg ps.textual])' 2>/dev/null | tail -1)/bin/python3}
for t in "ctxchart:test_ctxchart.py" "ctx-db:test_ctx_db.py" "ctx-instr:test_instr.py" "ctx-docs:test_docs.py" "ctxdata:test_ctxdata.py" "ctxui:test_ctxui.py"; do
  name=${t%%:*}; f=${t#*:}
  [ -x "$CTXPY" ] && { out=$(cd "$D/llm-ctx" && PYTHONDONTWRITEBYTECODE=1 timeout 300 "$CTXPY" -I "tests/$f" 2>&1); r=$?; printf '%-9s %s\n' "$name" "$(echo "$out" | tail -1)"; [ $r -eq 0 ] || { rc=1; echo "$out" | grep FAIL; }; }
done
# fleet(observe 호스트 간 비교): psycopg 가 있는 python 이면 임시 Postgres 통합까지, 아니면 순수 시험만(위 observe 묶음과 별개)
[ -x "$CTXPY" ] && { out=$(cd "$D/observe" && PYTHONDONTWRITEBYTECODE=1 timeout 300 "$CTXPY" -I tests/test_fleet.py 2>&1); r=$?; printf '%-9s %s\n' fleet "$(echo "$out" | tail -1)"; [ $r -eq 0 ] || { rc=1; echo "$out" | grep FAIL; }; }
# llm-sessions(실제 tmux·pty·화면): tmux 가 없으면 시험 파일이 알아서 건너뛴다(CLAUDE_TMUX_BIN 으로 지정 가능). UI 부분은 textual 이 있는 python 으로.
[ -x "$CTXPY" ] && { out=$(cd "$D/llm-sessions" && PYTHONDONTWRITEBYTECODE=1 timeout 300 "$CTXPY" -I tests/test_llm_sessions.py 2>&1); r=$?; printf '%-9s %s\n' llm-sessions "$(echo "$out" | tail -1)"; [ $r -eq 0 ] || { rc=1; echo "$out" | grep FAIL; }; }
find "$D" -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null
exit $rc
