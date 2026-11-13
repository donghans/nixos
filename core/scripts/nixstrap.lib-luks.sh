#!/usr/bin/env bash
# nixstrap.lib-luks.sh — 워크스테이션 LUKS 복구 암호 생성·확인(Phase 1)과 luksFormat/open/close(Phase 2)
#
# 비밀 취급 규칙 (계획 plan/nixstrap-luks §3-2):
#   - 암호는 셸 변수 _LUKS_PW 에만 둔다. export 하지 않고, 파일·로그·PARAMS_FILE 에 쓰지 않는다.
#   - cryptsetup 에는 printf '%s' (개행 없음) 로 stdin 에 흘린다. 인자·/dev/shm 파일 금지.
#   - 화면에는 단어·QR 을 보여 준 뒤 즉시 지운다(스크롤백 포함).
# 이 파일은 함수만 정의한다(source 용). 전역: _LUKS(true/false), _LUKS_NAME, _LUKS_PART, _LUKS_OPENED, _LUKS_PW.

_LUKS="${_LUKS:-false}"
_LUKS_NAME="${_LUKS_NAME:-cryptroot}"
_LUKS_PART="${_LUKS_PART:-}"
_LUKS_OPENED="${_LUKS_OPENED:-false}"
_LUKS_MAPPER_DIR="${_LUKS_MAPPER_DIR:-/dev/mapper}"
_LUKS_PW=""
_LUKS_WORDS="${_LUKS_WORDS:-8}"
_LUKS_MAX_TRIES=3

# 화면과 스크롤백을 지운다 (clear 바이너리에 의존하지 않음)
_luks_clear_screen() {
    printf '\033[2J\033[3J\033[H'
    if [ -n "${TMUX:-}" ]; then tmux clear-history 2>/dev/null || true; fi
}

luks_scrub() { _LUKS_PW=""; }

# 입력이 정규화 결과(소문자·공백 1칸)와 다르면 알린다. 부팅 때 initrd 의 암호 입력창은 정규화하지 않으므로
# 대문자·이중 공백으로 입력하면 여기서는 통과해도 부팅 때 열리지 않는다. 인자: 입력 원문, 정규화 결과
_luks_warn_if_unnormalized() {
    [ "$1" = "$2" ] || log_msg "Notice" "입력이 '소문자·단어 사이 공백 1칸' 형식과 달랐습니다(정규화해 비교함). 부팅 때의 암호 입력창은 정규화하지 않으니 종이에 적힌 그대로 소문자·공백 1칸으로 입력하세요."
}

# QR 이 들어갈 만큼 터미널이 크면 그린다. 아니면 조용히 생략(단어 표시는 항상 병행).
_luks_show_qr() {
    command -v qrencode >/dev/null 2>&1 || { log_msg "Notice" "qrencode 없음 — QR 생략(단어만 표시)"; return 0; }
    local _qr _qr_lines _qr_cols _cols _lines
    _qr=$(printf '%s' "$_LUKS_PW" | qrencode -t ANSIUTF8 -m 2 2>/dev/null) || { log_msg "Notice" "QR 생성 실패 — 단어만 표시"; return 0; }
    _qr_lines=$(printf '%s\n' "$_qr" | wc -l)
    _qr_cols=$(printf '%s\n' "$_qr" | sed 's/\x1b\[[0-9;]*m//g' | awk '{ if (length($0) > m) m = length($0) } END { print m + 0 }')
    _cols=$(tput cols 2>/dev/null || echo 80)
    _lines=$(tput lines 2>/dev/null || echo 24)
    if [ "$_qr_cols" -le "$_cols" ] && [ "$(( _qr_lines + 14 ))" -le "$_lines" ]; then
        printf '%s\n' "$_qr"
    else
        log_msg "Notice" "터미널이 작아 QR 생략(필요 ${_qr_cols}x$(( _qr_lines + 14 )), 현재 ${_cols}x${_lines}) — 단어만 표시"
    fi
}

_luks_show_secret() {
    local _bits
    _bits=$(python3 "$SCRIPT_DIR/nixstrap.lib-luks.py" bits "$_LUKS_WORDS")
    printf '\n'
    log_msg "Notice" "디스크 암호화 복구 암호 (영어 ${_LUKS_WORDS}단어, 약 ${_bits}비트) — 지금 종이/보안 저장소에 기록하세요."
    log_msg "Notice" "생성 시각 $(date '+%Y-%m-%d %H:%M')도 함께 적어 두세요(재실행 시 옛 암호와 구분). 이 화면은 암호 확인이 끝나면 다시 볼 수 없습니다."
    printf '\n'
    printf '%s\n' "$_LUKS_PW" | python3 "$SCRIPT_DIR/nixstrap.lib-luks.py" words | sed 's/^/        /'
    printf '\n'
    _luks_show_qr
    printf '\n'
}

# 대상 디스크 확인: 크기·모델·기존 시그니처를 보여 주고 경로를 직접 입력받는다. 인자: 디스크 경로
_luks_confirm_device() {
    local _dev=$1 _typed
    printf '\n'
    log_msg "Notice" "다음 디스크의 모든 데이터를 지우고 암호화합니다 (되돌릴 수 없음). 옛 데이터는 TRIM 으로 폐기를 시도하지만, 매체에 따라 완전히 지워진다는 보장은 없습니다:"
    lsblk -o NAME,SIZE,MODEL,FSTYPE,LABEL "$_dev" 2>/dev/null | sed 's/^/        /' || true
    wipefs -n "$_dev" 2>/dev/null | sed 's/^/        /' || true
    read -rp "$(_log_prompt)지울 디스크 경로를 그대로 입력하세요 ($_dev): " _typed
    if [ "$_typed" != "$_dev" ]; then
        log_msg "Error" "입력이 일치하지 않습니다 — 중단합니다. (디스크는 변경되지 않았습니다)"
        return 1
    fi
    return 0
}

# Phase 1: 생성 → 표시 → 기록 → 화면 지움 → 재입력 확인 → 디스크 경로 확인. 실패하면 return 1 (디스크 불변).
# 인자: 대상 디스크 경로(예 /dev/nvme0n1). 성공하면 _LUKS_PW 에 암호가 남는다(Phase 2 에서 사용 후 luks_scrub).
luks_generate_and_confirm() {
    local _disk=$1 _try _typed _want _raw
    _LUKS_PW=$(python3 "$SCRIPT_DIR/nixstrap.lib-luks.py" gen "$_LUKS_WORDS") || { log_msg "Error" "복구 암호 생성 실패"; _LUKS_PW=""; return 1; }
    python3 "$SCRIPT_DIR/nixstrap.lib-luks.py" check-wordlist >/dev/null || { log_msg "Error" "단어 목록 무결성 오류"; _LUKS_PW=""; return 1; }
    _luks_show_secret
    log_msg "Notice" "ssh 로 접속 중이면 클라이언트 터미널 스크롤백에 암호가 남습니다. 설치는 노트북 본체 화면에서 하세요."
    read -rp "$(_log_prompt)기록을 마쳤으면 Enter (화면이 지워집니다): " _
    _luks_clear_screen
    _want=$(printf '%s\n' "$_LUKS_PW" | python3 "$SCRIPT_DIR/nixstrap.lib-luks.py" normalize)
    for (( _try = 1; _try <= _LUKS_MAX_TRIES; _try++ )); do
        log_msg "Notice" "기록한 종이를 보고 복구 암호를 다시 입력하세요 (화면 복사 금지) [$_try/$_LUKS_MAX_TRIES]:"
        read -rsp "$(_log_prompt)복구 암호: " _typed
        printf '\n'
        _raw=$_typed
        _typed=$(printf '%s\n' "$_typed" | python3 "$SCRIPT_DIR/nixstrap.lib-luks.py" normalize)
        _luks_warn_if_unnormalized "$_raw" "$_typed"; _raw=""
        if [ "$_typed" = "$_want" ]; then
            _typed=""; _want=""
            _luks_confirm_device "$_disk" || { _LUKS_PW=""; return 1; }
            return 0
        fi
        log_msg "Error" "일치하지 않습니다."
        if [ "$_try" -lt "$_LUKS_MAX_TRIES" ]; then
            _luks_show_secret
            read -rp "$(_log_prompt)다시 확인했으면 Enter: " _
            _luks_clear_screen
        fi
    done
    _typed=""; _want=""; _LUKS_PW=""
    log_msg "Error" "복구 암호 확인에 ${_LUKS_MAX_TRIES}회 실패 — 중단합니다. (디스크는 변경되지 않았습니다)"
    return 1
}

# Phase 2: luksFormat + open. 인자: LUKS 파티션 경로. 매퍼 이름은 _LUKS_NAME.
luks_format_open() {
    local _part=$1
    [ -n "$_LUKS_PW" ] || { log_msg "Error" "복구 암호가 없습니다(Phase 1 확인 누락)"; return 1; }
    _LUKS_PART="$_part"
    log_msg "Disk" "LUKS2 포맷: $_part"
    printf '%s' "$_LUKS_PW" | cryptsetup luksFormat --type luks2 --batch-mode --key-file=- "$_part" || return 1
    printf '%s' "$_LUKS_PW" | cryptsetup open --key-file=- "$_part" "$_LUKS_NAME" || return 1
    _LUKS_OPENED=true
    luks_scrub
}

# 포맷 직후: 종이를 보고 다시 입력해 열림을 검증한다(--test-passphrase). 최대 _LUKS_MAX_TRIES 회.
luks_verify_typed() {
    local _part=$1 _try _typed _raw
    for (( _try = 1; _try <= _LUKS_MAX_TRIES; _try++ )); do
        log_msg "Notice" "종이의 복구 암호로 열림 검증 [$_try/$_LUKS_MAX_TRIES]:"
        read -rsp "$(_log_prompt)복구 암호: " _typed
        printf '\n'
        _raw=$_typed
        _typed=$(printf '%s\n' "$_typed" | python3 "$SCRIPT_DIR/nixstrap.lib-luks.py" normalize)
        _luks_warn_if_unnormalized "$_raw" "$_typed"; _raw=""
        if printf '%s' "$_typed" | cryptsetup open --test-passphrase --key-file=- "$_part"; then
            _typed=""
            log_msg "Success" "복구 암호로 열림 확인"
            return 0
        fi
        log_msg "Error" "열리지 않습니다."
    done
    _typed=""
    return 1
}

# LUKS 를 고른 실행에서만 매퍼를 닫는다(LUKS 아니오 실행이 열려 있는 시스템의 cryptroot 를 닫지 않게).
# 시작 시 정리(이전 시도의 남은 매퍼)와 종료 시 정리에 모두 쓴다. 닫을 게 없거나 실패해도 계속한다.
luks_close() {
    if [ "$_LUKS" = true ] && [ -e "$_LUKS_MAPPER_DIR/$_LUKS_NAME" ]; then
        cryptsetup close "$_LUKS_NAME" 2>/dev/null || log_msg "Notice" "cryptsetup close 실패(사용 중?): $_LUKS_MAPPER_DIR/$_LUKS_NAME"
    fi
    _LUKS_OPENED=false
    return 0
}

# 설치 직후 LUKS 헤더 백업 (기본 예). 대상: USB 파티션(Ventoy 데이터 파티션 등) / 마운트된 디렉터리 / scp.
# 헤더는 노트북 디스크 밖에 둔다. 실패·건너뜀은 설치를 막지 않는다(경고). 인자: LUKS 파티션 경로.
luks_offer_header_backup() {
    local _part=$1 _ans _tmpdir _mnt _out _sel _target _dev _size _fs _label _pdisk
    local -a _devs=() _labels=() _opts=()
    printf '\n'
    log_msg "Notice" "LUKS 헤더가 손상되면 복구 암호가 있어도 데이터를 열 수 없습니다. 헤더를 디스크 밖(USB 등)에 백업해 두는 것을 권장합니다."
    read -rp "$(_log_prompt)지금 헤더를 백업하시겠습니까? (Y/n): " _ans || _ans=n
    if [[ "${_ans:-Y}" =~ ^[Nn]$ ]]; then
        log_msg "Notice" "백업 건너뜀 — 나중에 'luksctl.py backup-header $_part <디렉터리>' 로 할 수 있습니다."
        return 0
    fi
    while true; do
        _devs=(); _labels=()
        # JSON 으로 읽는다: `lsblk -r` + read 는 빈 레이블 칸을 합쳐 버려 레이블 없는 USB 가 빠진다.
        # 설치 대상 디스크 자신의 파티션은 후보에서 뺀다(디스크 밖 백업의 의미가 없어짐).
        _pdisk=$(lsblk -dnpo PKNAME "$_part" 2>/dev/null | head -1 || true)
        while IFS=$'\x1f' read -r _dev _size _fs _label; do
            [ -n "$_dev" ] || continue
            _devs+=("$_dev"); _labels+=("$(printf '%-18s %8s [%-6s] %s' "$_dev" "$_size" "$_fs" "${_label:-<레이블 없음>}")")
        done < <(lsblk -lJpo NAME,SIZE,FSTYPE,LABEL,HOTPLUG,PKNAME 2>/dev/null | jq -r --arg pd "$_pdisk" '
            .blockdevices[]
            | select(.fstype != null and (.hotplug == true or .hotplug == 1 or .hotplug == "1"))
            | select($pd == "" or (.pkname != $pd and .name != $pd))
            | [.name, .size, .fstype, (.label // "")] | join("\u001f")')
        _opts=("${_labels[@]}" "+ 이미 마운트된 디렉터리 경로 입력" "+ 다른 컴퓨터로 scp (user@host:경로)" "건너뜀")
        _pick "헤더 백업 위치 (USB 데이터 파티션 권장; exFAT 등은 파일 권한이 없음을 감안):" "${_opts[@]}"
        _sel=$REPLY
        _out=""
        if [ "$_sel" -eq "${#_devs[@]}" ]; then
            read -rp "$(_log_prompt)디렉터리 경로: " _target || _target=""
            if [ -d "$_target" ]; then
                _out=$(python3 "$SCRIPT_DIR/luksctl.py" backup-header "$_part" "$_target") || _out=""
            else
                log_msg "Error" "디렉터리가 아닙니다: $_target"
            fi
        elif [ "$_sel" -eq "$(( ${#_devs[@]} + 1 ))" ]; then
            read -rp "$(_log_prompt)scp 대상 (예: user@host:/path/): " _target || _target=""
            _tmpdir=$(mktemp -d /tmp/luks-hdr-XXXXXX)
            _out=$(python3 "$SCRIPT_DIR/luksctl.py" backup-header "$_part" "$_tmpdir") || _out=""
            if [ -n "$_out" ] && [ -n "$_target" ]; then
                scp -- "$_out" "$_target" || { log_msg "Error" "scp 실패"; _out=""; }
            else
                _out=""
            fi
            rm -rf "$_tmpdir"
        elif [ "$_sel" -eq "$(( ${#_devs[@]} + 2 ))" ]; then
            log_msg "Notice" "백업 건너뜀 — 나중에 'luksctl.py backup-header $_part <디렉터리>' 로 할 수 있습니다."
            return 0
        else
            _mnt=$(mktemp -d /tmp/luks-hdr-mnt-XXXXXX)
            if mount "${_devs[$_sel]}" "$_mnt"; then
                _out=$(python3 "$SCRIPT_DIR/luksctl.py" backup-header "$_part" "$_mnt") || _out=""
                sync
                umount "$_mnt" || log_msg "Notice" "umount 실패: $_mnt (수동으로 정리하세요)"
            else
                log_msg "Error" "마운트 실패: ${_devs[$_sel]}"
            fi
            rmdir "$_mnt" 2>/dev/null || true
        fi
        if [ -n "$_out" ]; then
            log_msg "Success" "헤더 백업 완료: ${_out##*/}"
            log_msg "Notice" "※ TPM2/FIDO2 등으로 슬롯을 바꾸면 이 백업은 옛 암호로만 열립니다 — 그 뒤 다시 백업하세요."
            return 0
        fi
        read -rp "$(_log_prompt)백업에 실패했습니다. 다시 시도하시겠습니까? (Y/n): " _ans || _ans=n
        [[ "${_ans:-Y}" =~ ^[Nn]$ ]] && { log_msg "Notice" "백업하지 않고 계속합니다."; return 0; }
    done
}
