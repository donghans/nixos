# bw_lib.sh — Bitwarden 켜고 끄기 도구(abab 스크립트가 불러 씀). 끌 때는 PID 로만(찾은 뒤 args 를 확인하고 그 PID 만 종료), 켤 때는 systemd 사용자 단위로(내 셸 환경 오염 방지).
BW_RE='bitwarden-desktop-[^ ]*/opt/Bitwarden'
_bw_pids() { pgrep -u "$(id -u)" -f "$BW_RE" | while read -r p; do ps -o args= -p "$p" 2>/dev/null | grep -q -- '--type=' || echo "$p"; done; }   # 메인 프로세스만(자식 --type= 제외)
_bw_running() { [ -n "$(_bw_pids)" ]; }
bw_start() {
    _bw_running && return 0
    systemctl --user reset-failed ab-bitwarden 2>/dev/null
    systemd-run --user --collect --unit=ab-bitwarden env -u LD_LIBRARY_PATH "${BITWARDEN:-$HOME/.nix-profile/bin/bitwarden}" --autostart >/dev/null 2>&1
    for _n in 1 2 3 4 5 6 7 8 9 10; do _bw_running && return 0; sleep 2; done
    return 1
}
bw_stop() {
    if systemctl --user is-active --quiet ab-bitwarden; then systemctl --user stop ab-bitwarden; fi
    for p in $(_bw_pids); do
        args=$(ps -o args= -p "$p" 2>/dev/null)
        case "$args" in *bitwarden-desktop*/opt/Bitwarden*) kill -TERM "$p" ;; *) echo "FAIL: PID $p 가 Bitwarden 이 아님: $args"; return 1 ;; esac
    done
    for _n in 1 2 3 4 5 6 7 8 9 10; do _bw_running || return 0; sleep 1; done
    return 1
}
