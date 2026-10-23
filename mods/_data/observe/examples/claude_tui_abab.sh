#!/bin/sh
# Claude Code TUI 의 전력 비용 — kitty 창에 실제 TUI 를 띄워 번갈아 잰다(덮개 열림·화면 켜짐, 무입력).
#   MODE=motion   A=모션 보통(spinner 애니메이션) / B=모션 줄임(prefersReducedMotion) — 둘 다 「일하는 중」 TUI (T19)
#   MODE=opacity  A=kitty 배경 투명도 0.95(현재 설정) / B=1.0(불투명)(CT_OPACITY_B=0.95 이면 널 시험) — 둘 다 일하는 TUI, 모션 줄임 (덮개 열림에서 의미 — 합성·패널 갱신 비용 가설)
#   MODE=park     A=일하는 TUI 가 보이는 워크스페이스 / B=같은 TUI 를 두고 빈 워크스페이스(CT_PARK_WS, 기본 7)로 이동 — 덮개 닫힘(RC) 에서 화면 갱신 비용을 없앨 수 있는지(출력·DPMS 는 건드리지 않음: 이 기기는 dpms 후 화면이 안 켜지는 문제가 있어 쓰지 않는다)
#   MODE=activity A=한가한 TUI(프롬프트만 떠 있음) / B=일하는 TUI(도구 실행 중 spinner·타이머가 돎) — 둘 다 모션 줄임 (T18)
# 「일하는 중」은 Bash 도구로 `python3 -c time.sleep` 을 실행시켜 만든다(단독 `sleep` 은 Claude 의 Bash 차단 규칙에 걸릴 때가 있다 — 2026-10-23) — 모델 호출은 시작 때 한 번뿐(haiku)이라 API 한도를 거의 쓰지 않고, TUI 는 도구가 도는 내내 spinner 를 갱신한다.
# 사용: ABAB_AC_MODE=1 MODE=motion SEG=300 PAIRS=3 SETTLE=90 claude_tui_abab.sh
# 훅·ctx 기록을 피하려고 --settings 는 모션 키만 든 최소 파일을 쓴다(저장소 nix 설정의 차이도 prefersReducedMotion 키 하나뿐).
SETTLE=${SETTLE:-90}   # abab_lib.sh 가 SETTLE 기본값(40)을 먼저 채우므로 불러오기 전에 정한다
. "$(dirname "$0")/abab_lib.sh"
MODE=${MODE:?MODE=motion|activity}
UNIT=${CT_UNIT:-claude-tui-ab}
WORKDIR=${CT_WORKDIR:-$HOME/nixos}                 # Claude 가 이미 신뢰한 디렉터리(처음 보는 폴더면 신뢰 확인창이 뜸)
HOLD=${CT_HOLD:-$((SEG + SETTLE + 60))}            # 일하는 TUI 가 구간 내내 도구를 실행 중이도록 sleep 길이
SOCK=${CT_SOCK:-${XDG_RUNTIME_DIR:-/tmp}/claude-tui-ab.sock}
CT_WS=${CT_WS:-9}; CT_PARK_WS=${CT_PARK_WS:-7}                                  # 시험 전용 워크스페이스(사용자의 작업 워크스페이스와 분리)
WS0=$(hyprctl activeworkspace -j 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" 2>/dev/null); WS0=${WS0:-1}
export PATH="$PATH:$HOME/.nix-profile/bin:/run/current-system/sw/bin"   # kitten(kitty 와 같은 곳)·hyprctl
SET_DIR=$(mktemp -d)
echo '{"prefersReducedMotion":true}' > "$SET_DIR/reduced.json"; echo '{}' > "$SET_DIR/normal.json"
_ct_stop() { systemctl --user stop "$UNIT" 2>/dev/null; systemctl --user reset-failed "$UNIT" 2>/dev/null; rm -f "$SOCK"; return 0; }
_ct_ws() { hyprctl dispatch "hl.dsp.focus({ workspace = $1 })" >/dev/null 2>&1; }
_ct_start() {   # $1=normal|reduced  $2=work|idle
    _ct_stop
    # TUI 는 보이는 워크스페이스에 있어야 갱신된다(안 보이면 프레임이 멈춰 측정이 무효). 이 시험 동안만 전용 워크스페이스로 전환한다.
    _ct_ws "$CT_WS"
    # kitty 는 소켓 전용 원격 제어로 띄우고(그 창에만 텍스트를 보낸다 — 포커스·다른 창과 무관), TUI 는 인자 프롬프트를 자동 제출하지 않으므로 아래에서 직접 입력한다.
    systemd-run --user --unit="$UNIT" --collect --quiet \
        -E WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}" -E HYPRLAND_INSTANCE_SIGNATURE="$HYPRLAND_INSTANCE_SIGNATURE" \
        -E BASH_DEFAULT_TIMEOUT_MS=$((HOLD * 1000 + 60000)) -E BASH_MAX_TIMEOUT_MS=$((HOLD * 1000 + 60000)) \
        -p WorkingDirectory="$WORKDIR" \
        env -u LD_LIBRARY_PATH kitty --class claude-tui-ab -o background_opacity="${CT_OPACITY:-0.95}" -o allow_remote_control=socket-only --listen-on "unix:$SOCK" sh -c \
        "exec claude --model haiku --settings '$SET_DIR/$1.json' --allowedTools='Bash(python3:*)'" >/dev/null 2>&1 || return 1
    _i=0; while [ "$_i" -lt 40 ]; do kitten @ --to "unix:$SOCK" get-text 2>/dev/null | grep -q 'Haiku' && break; sleep 1; _i=$((_i + 1)); done
    [ "$_i" -lt 40 ] || { echo "FAIL: Claude TUI 가 40초 안에 뜨지 않음"; return 1; }
    sleep 2
    [ "$2" = work ] || return 0
    kitten @ --to "unix:$SOCK" send-text "Bash 도구로 \`python3 -c 'import time; time.sleep($HOLD)'\` 를 그대로 한 번만 실행하고(백그라운드 금지), 끝나면 '완료' 한 단어로만 답해." || return 1
    sleep 1; kitten @ --to "unix:$SOCK" send-text $'\r'
}
_ct_active_ws() { hyprctl activeworkspace -j 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin)['id'])" 2>/dev/null; }
_ct_state() {   # 화면 상태 확인: kitty 창이 있고 claude 프로세스가 있는지, 일하는 쪽이면 sleep 자식이 있는지. 값: idle|work|none
    _cp=$(systemctl --user show -p MainPID --value "$UNIT" 2>/dev/null)
    [ -n "$_cp" ] && [ "$_cp" != 0 ] || { echo none; return; }
    if pgrep -f "time[.]sleep[(]$HOLD[)]" >/dev/null 2>&1; then echo work; else pgrep -f "claude --model haiku" >/dev/null 2>&1 && echo idle || echo none; fi
}
_ct_wait_state() {   # $1=기대 상태, 최대 60초(모델 응답 후 도구가 시작될 때까지)
    _i=0; while [ "$_i" -lt 60 ]; do [ "$(_ct_state)" = "$1" ] && return 0; sleep 1; _i=$((_i + 1)); done; return 1
}
case "$MODE" in
    motion)
        abab_set_a()    { _ct_start normal work; }
        abab_set_b()    { _ct_start reduced work; }
        abab_verify_a() { _ct_wait_state work; }
        abab_verify_b() { _ct_wait_state work; } ;;
    activity)
        abab_set_a()    { _ct_start reduced idle; }
        abab_set_b()    { _ct_start reduced work; }
        abab_verify_a() { sleep 15; [ "$(_ct_state)" = idle ]; }
        abab_verify_b() { _ct_wait_state work; } ;;
    opacity)
        abab_set_a()    { CT_OPACITY=0.95 _ct_start reduced work; }
        abab_set_b()    { CT_OPACITY=${CT_OPACITY_B:-1} _ct_start reduced work; }   # CT_OPACITY_B=0.95 로 주면 A·B 가 같은 널(null) 시험 — 이 환경의 소음 폭을 잰다
        abab_verify_a() { _ct_wait_state work; }
        abab_verify_b() { _ct_wait_state work; } ;;
    park)
        abab_set_a()    { _ct_start reduced work; }
        abab_set_b()    { _ct_start reduced work && sleep 3 && _ct_ws "$CT_PARK_WS"; }   # TUI 는 CT_WS 에서 일하고, 보이는 쪽만 빈 워크스페이스로
        abab_verify_a() { _ct_wait_state work && [ "$(_ct_active_ws)" = "$CT_WS" ]; }
        abab_verify_b() { _ct_wait_state work && [ "$(_ct_active_ws)" = "$CT_PARK_WS" ]; } ;;
    *) echo "MODE=motion|activity|opacity|park"; exit 2 ;;
esac
abab_restore()  { _ct_stop; rm -rf "$SET_DIR"; _ct_ws "$WS0"; echo "Claude 시험 창 정리 · 워크스페이스 $WS0 로 복귀 · 남은 claude-tui-ab 유닛: $(systemctl --user list-units "$UNIT*" --no-legend | wc -l)"; }
abab_run
