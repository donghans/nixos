#!/usr/bin/env bash
# nixstrap.task-input.sh — Phase 1 입력 수집 함수 (레포·호스트·프리셋·패스워드·세션 관리)

# ── 입력 수집 ──────────────────────────────────────────────────────────────────

ask_repo_and_clone() {
    local _prompt _input
    while true; do
        if [ -n "${NIXOS_REPO:-}" ]; then
            _prompt="$(_log_prompt)레포지터리 [${NIXOS_REPO}]: "
        else
            _prompt="$(_log_prompt)레포지터리 (예: user/nixos): "
        fi
        read -rp "$_prompt" _input
        NIXOS_REPO="${_input:-${NIXOS_REPO:-}}"
        if [ -z "$NIXOS_REPO" ]; then
            log_msg "Error" "레포지터리는 필수입니다."
            continue
        fi
        rm -rf "$REPO_TMP"
        log_msg "Git" "github.com/$NIXOS_REPO 클론 중..."
        log_exec "git" ">" "git clone"
        if git clone "https://github.com/$NIXOS_REPO.git" "$REPO_TMP"; then
            log_exec "git" "<" "git clone"
            # _base.toml의 git.nixosRepo와 비교하여 불일치 시 치환 여부 확인
            local _toml_repo _replace
            _toml_repo=$(python3 "$SCRIPT_DIR/nixstrap.lib-repo.py" check-repo "$REPO_TMP")
            if [ -n "$_toml_repo" ] && [ "$_toml_repo" != "$NIXOS_REPO" ]; then
                log_msg "Notice" "_base.toml의 git.nixosRepo = '$_toml_repo'"
                read -rp "$(_log_prompt)'${NIXOS_REPO}'로 업데이트하시겠습니까? (Y/n): " _replace
                _replace="${_replace:-Y}"
                if [[ "$_replace" =~ ^[Yy]$ ]]; then
                    python3 "$SCRIPT_DIR/nixstrap.lib-repo.py" update-repo "$REPO_TMP" "$NIXOS_REPO"
                    log_msg "Config" "_base.toml 업데이트: git.nixosRepo = '$NIXOS_REPO'"
                fi
            fi
            break
        else
            log_msg "Error" "클론 실패. 주소를 확인하고 다시 시도하세요."
            NIXOS_REPO=""
        fi
    done
}

select_host() {
    local host_data
    host_data=$(python3 "$SCRIPT_DIR/nixstrap.lib-repo.py" list-hosts "$REPO_TMP")

    # 로컬 설치 가능 호스트(selectable)와 원격 전용 호스트(footer)를 분리
    local -a _sel_names=() _sel_labels=()
    _PICK_FIXED_FOOTER=()
    while IFS='|' read -r _name _type _preset_val _flag; do
        [ -z "$_name" ] && continue
        if [ "$_flag" = "remote" ]; then
            _PICK_FIXED_FOOTER+=("$(printf "%-24s [remote ] rnixup / rnixstrap" "$_name")")
        else
            _sel_names+=("$_name")
            _sel_labels+=("$(printf "%-24s [%-7s] %s" "$_name" "$_type" "$_preset_val")")
        fi
    done <<< "$host_data"

    local -a _all_labels
    if [ ${#_sel_labels[@]} -gt 0 ]; then
        _all_labels=("${_sel_labels[@]}" "+ 새 호스트명 입력")
    else
        _all_labels=("+ 새 호스트명 입력")
    fi

    printf "\n"
    _pick "호스트 선택:" "${_all_labels[@]}"
    local _sel=$REPLY
    _PICK_FIXED_FOOTER=()  # 사용 후 초기화

    if [ "$_sel" -eq "${#_sel_names[@]}" ]; then
        _HOST_IS_NEW=true
        _HOST_TYPE=""
        _HOST_PRESET_FROM_REPO=""
        _HOST_USERNAME=""
        local _hinput
        read -rp "$(_log_prompt)새 호스트명: " _hinput
        HOST="${_hinput:-}"
        if [ -z "$HOST" ]; then
            log_msg "Error" "호스트명은 필수입니다."
            select_host
            return
        fi
        if [ -f "$REPO_TMP/hosts/${HOST}.toml" ]; then
            log_msg "Error" "'$HOST'는 이미 존재합니다. 위 목록에서 선택하세요."
            select_host
            return
        fi
        ask_host_username
    else
        _HOST_IS_NEW=false
        _HOST_USERNAME=""
        HOST="${_sel_names[$_sel]}"
        _HOST_TYPE=$(echo "$host_data" | grep "^${HOST}|" | cut -d'|' -f2)
        _HOST_PRESET_FROM_REPO=$(echo "$host_data" | grep "^${HOST}|" | cut -d'|' -f3)
        _PRESET="$_HOST_PRESET_FROM_REPO"
    fi
}

ask_host_username() {
    local _base_user _input
    _base_user=$(python3 "$SCRIPT_DIR/nixstrap.lib-repo.py" username "$REPO_TMP" 2>/dev/null || true)
    read -rp "$(_log_prompt)사용자명 [${_base_user:-_base.toml}]: " _input
    _HOST_USERNAME="${_input:-}"
}

ask_preset() {
    # iso.toml 제외 — 설치 컨텍스트에서는 iso 프리셋 사용 불가
    local -a _preset_opts=()
    while IFS= read -r _pname; do
        [ -z "$_pname" ] && continue
        _preset_opts+=("$_pname")
    done < <(python3 "$SCRIPT_DIR/nixstrap.lib-repo.py" list-presets "$REPO_TMP")

    # 레포에 프리셋이 없는 경우 폴백 (정상적으론 발생 안 함)
    if [ ${#_preset_opts[@]} -eq 0 ]; then
        _preset_opts=("workstation" "server")
    fi
    printf "\n"
    _pick "프리셋 선택:" "${_preset_opts[@]}"
    _PRESET="${_preset_opts[$REPLY]}"
}

ask_state_version() {
    local _input
    printf "\n"
    log_msg "Notice" "NixOS 릴리스에 고정하시겠습니까? (예: 25.11 — 빈 칸이면 rolling):"
    read -rp "$(_log_prompt)stateVersion: " _input
    _STATE_VERSION="${_input:-}"
    if [ -n "$_STATE_VERSION" ]; then
        log_msg "Config" "stateVersion: $_STATE_VERSION (stable lock)"
    else
        log_msg "Config" "stateVersion: (없음 — rolling)"
    fi
}

ask_password() {
    local _preview_user _pw _pw2
    _preview_user=$(python3 "$SCRIPT_DIR/nixstrap.lib-repo.py" username "$REPO_TMP" 2>/dev/null || true)
    local _label="${_preview_user:-user}"
    printf "\n"
    log_msg "Notice" "'$_label' 로그인 비밀번호 설정 (Enter 두 번 누르면 건너뜀):"
    while true; do
        read -rsp "$(_log_prompt)비밀번호: " _pw
        printf "\n"
        if [ -z "$_pw" ]; then
            read -rp "$(_log_prompt)비밀번호 설정을 건너뛰시겠습니까? (y/N): " _skip
            if [[ "${_skip:-N}" =~ ^[Yy]$ ]]; then
                _USER_PASSWORD=""
                log_msg "Notice" "건너뜀 — 비밀번호가 설정되지 않습니다."
                break
            fi
            continue
        fi
        read -rsp "$(_log_prompt)확인:     " _pw2
        printf "\n"
        if [ "$_pw" = "$_pw2" ]; then
            _USER_PASSWORD="$_pw"
            log_msg "Config" "비밀번호 설정 완료."
            break
        fi
        log_msg "Error" "비밀번호가 일치하지 않습니다. 다시 입력하세요."
    done
}

# ── 세션 관리 ──────────────────────────────────────────────────────────────────

show_summary() {
    local _fmt_boot _fmt_root
    printf "\n"
    log_msg "Review" "설치 설정 확인:"
    printf "  1. %-11s:  %s\n" "레포지터리" "${NIXOS_REPO:-(미설정)}"

    if [ -n "${HOST:-}" ]; then
        if [ "$_HOST_IS_NEW" = true ]; then
            if [ "$_IS_VM" = true ]; then
                printf "  2. %-11s:  %s  (신규, VM: incus-guest=on incus=off)\n" "호스트명" "$HOST"
            else
                printf "  2. %-11s:  %s  (신규)\n" "호스트명" "$HOST"
            fi
            local _uname_display="${_HOST_USERNAME:-_base.toml에서}"
            printf "     %-11s   사용자명: %s\n" "" "$_uname_display"
        else
            printf "  2. %-11s:  %s  [%s] %s\n" "호스트명" "$HOST" "${_HOST_TYPE:-?}" "${_HOST_PRESET_FROM_REPO:-?}"
            if [ "$_IS_VM" = true ]; then
                printf "     %-11s   VM 감지됨 — host.toml 기존 파일 유지, incus 설정 변경 없음\n" ""
            fi
        fi
    else
        printf "  2. %-11s:  %s\n" "호스트명" "(미설정)"
    fi

    if [[ "${_PART_MODE:-}" == "1" ]]; then
        _fmt_boot="아니오"; [[ "${FORMAT_BOOT:-}" =~ ^[Yy]$ ]] && _fmt_boot="예"
        _fmt_root="아니오"; [[ "${FORMAT_ROOT:-}" =~ ^[Yy]$ ]] && _fmt_root="예"
        printf "  3. %-11s:  기존  boot=%s  root=%s\n" \
            "파티션" "${BOOT_PART:-(미설정)}" "${ROOT_PART:-(미설정)}"
        printf "     %-11s   부트 포맷: %s  루트 포맷: %s\n" "" "$_fmt_boot" "$_fmt_root"
    elif [[ "${_PART_MODE:-}" == "2" ]]; then
        printf "  3. %-11s:  신규  %s -> %s (EFI %s), %s (root)\n" \
            "파티션" "${_DISK:-(미설정)}" \
            "${BOOT_PART:-(미설정)}" "${_BOOT_SIZE:-?}" "${ROOT_PART:-(미설정)}"
        if [[ "${_WIPE:-false}" == "true" ]]; then
            printf "     %-11s   ${RED}전체 디스크 초기화${NC}\n" ""
        fi
    else
        printf "  3. %-11s:  %s\n" "파티션" "(미설정)"
    fi

    if [ "$_HOST_IS_NEW" = true ]; then
        local _sv_display="${_STATE_VERSION:-rolling}"
        printf "  4. %-11s:  %s  (stateVersion: %s)\n" "프리셋" "${_PRESET:-workstation}" "$_sv_display"
    else
        printf "  4. %-11s:  %s  (레포에서)\n" "프리셋" "${_HOST_PRESET_FROM_REPO:-?}"
    fi
    printf "  %s\n" "─────────────────────────────────────────────"
}

save_params() {
    {
        printf 'NIXOS_REPO=%s\n'              "$NIXOS_REPO"
        printf 'HOST=%s\n'                    "$HOST"
        printf '_HOST_IS_NEW=%s\n'            "$_HOST_IS_NEW"
        printf '_HOST_TYPE=%s\n'              "$_HOST_TYPE"
        printf '_HOST_PRESET_FROM_REPO=%s\n'  "$_HOST_PRESET_FROM_REPO"
        printf '_PRESET=%s\n'                 "$_PRESET"
        printf '_STATE_VERSION=%s\n'          "$_STATE_VERSION"
        printf '_HOST_USERNAME=%s\n'          "$_HOST_USERNAME"
        printf '_PART_MODE=%s\n'              "$_PART_MODE"
        printf '_NEW_PARTITIONS=%s\n'         "$_NEW_PARTITIONS"
        printf 'BOOT_PART=%s\n'               "$BOOT_PART"
        printf 'ROOT_PART=%s\n'               "$ROOT_PART"
        printf 'FORMAT_BOOT=%s\n'             "$FORMAT_BOOT"
        printf 'FORMAT_ROOT=%s\n'             "$FORMAT_ROOT"
        printf '_DISK=%s\n'                   "$_DISK"
        printf '_WIPE=%s\n'                   "$_WIPE"
        printf '_PART_START=%s\n'             "$_PART_START"
        printf '_PART_END=%s\n'               "$_PART_END"
        printf '_BOOT_SIZE=%s\n'              "$_BOOT_SIZE"
        printf '_BOOT_END=%s\n'               "$_BOOT_END"
        printf '_NEW_BOOT_NUM=%s\n'           "$_NEW_BOOT_NUM"
        printf '_NEW_ROOT_NUM=%s\n'           "$_NEW_ROOT_NUM"
    } > "$PARAMS_FILE"
    log_msg "Config" "세션 저장: $PARAMS_FILE"
}

load_params() {
    [ -f "$PARAMS_FILE" ] || return 1

    # 파일을 source하지 않고 핵심 필드만 읽어 표시
    local _repo _host _mode _boot _root
    _repo=$(grep '^NIXOS_REPO='  "$PARAMS_FILE" | cut -d= -f2-)
    _host=$(grep '^HOST='        "$PARAMS_FILE" | cut -d= -f2-)
    _mode=$(grep '^_PART_MODE='  "$PARAMS_FILE" | cut -d= -f2-)
    _boot=$(grep '^BOOT_PART='   "$PARAMS_FILE" | cut -d= -f2-)
    _root=$(grep '^ROOT_PART='   "$PARAMS_FILE" | cut -d= -f2-)

    log_msg "Notice" "이전 세션 발견:"
    printf "     repo=%-30s host=%s\n" "$_repo" "$_host"
    printf "     mode=%-5s boot=%-20s root=%s\n" "$_mode" "$_boot" "$_root"

    _pick "이전 세션을 불러오시겠습니까?" \
        "예  — 불러와서 확인" \
        "아니오  — 새로 시작 (저장된 세션 삭제)"

    if [ "$REPLY" -eq 0 ]; then
        # shellcheck disable=SC1090
        source "$PARAMS_FILE"
        log_msg "Config" "세션 로드됨."
        return 0
    else
        rm -f "$PARAMS_FILE"
        return 1
    fi
}

review_loop() {
    local _review=""
    while true; do
        show_summary
        read -rp "$(_log_prompt)Enter=설치  1-4=수정  s=저장  q=종료: " _review || {
            # Ctrl+C 인터럽트: _trap_int가 경고 처리함. 타임아웃 리셋 없이 루프 재진입.
            _review=""
            continue
        }
        _TRAP_INT_WARNED_AT=0  # 정상 입력 성공 → 타임아웃 리셋 (다음 Ctrl+C는 다시 경고)
        case "${_review:-}" in
            "")
                if [ -z "${HOST:-}" ]; then
                    log_msg "Error" "호스트명이 필요합니다. 항목 2를 수정하세요."
                    continue
                fi
                if [ -z "${BOOT_PART:-}" ] || [ -z "${ROOT_PART:-}" ]; then
                    log_msg "Error" "파티션 정보가 불완전합니다. 항목 3을 수정하세요."
                    continue
                fi
                save_params
                break
                ;;
            s|S)
                if [ -z "${HOST:-}" ]; then
                    log_msg "Error" "호스트명이 필요합니다. 항목 2를 수정하세요."
                    continue
                fi
                if [ -z "${BOOT_PART:-}" ] || [ -z "${ROOT_PART:-}" ]; then
                    log_msg "Error" "파티션 정보가 불완전합니다. 항목 3을 수정하세요."
                    continue
                fi
                save_params
                log_msg "Done" "$PARAMS_FILE 에 저장됨. 재실행하면 설치를 계속할 수 있습니다."
                exit 0
                ;;
            1)
                ask_repo_and_clone
                select_host
                if [ "$_HOST_IS_NEW" = true ]; then ask_preset; fi
                ;;
            2)
                select_host
                if [ "$_HOST_IS_NEW" = true ]; then ask_preset; fi
                ;;
            3) ask_partitions ;;
            4)
                if [ "$_HOST_IS_NEW" = true ]; then
                    ask_preset
                    ask_state_version
                else
                    log_msg "Notice" "기존 호스트의 프리셋은 레포에서 고정됩니다."
                fi
                ;;
            q|Q) log_msg "Error" "취소됨."; exit 1 ;;
            *) log_msg "Notice" "1-4로 수정, s로 저장, Enter로 설치를 진행하세요." ;;
        esac
    done
}
