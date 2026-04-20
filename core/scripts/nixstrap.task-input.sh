#!/usr/bin/env bash
# nixstrap.task-input.sh — Phase 1 입력 수집 함수 (레포·호스트·프리셋·패스워드·세션 관리)

# ── 입력 수집 ──────────────────────────────────────────────────────────────────

ask_repo_and_clone() {
    local _prompt _input
    while true; do
        if [ -n "${NIXOS_REPO:-}" ]; then
            _prompt="$(log_prompt)repository [${NIXOS_REPO}]: "
        else
            _prompt="$(log_prompt)repository (e.g. user/nixos): "
        fi
        read -rp "$_prompt" _input
        NIXOS_REPO="${_input:-${NIXOS_REPO:-}}"
        if [ -z "$NIXOS_REPO" ]; then
            log_msg "Error" "repository is required."
            continue
        fi
        rm -rf "$REPO_TMP"
        log_msg "Git" "cloning github.com/$NIXOS_REPO ..."
        log_exec "git" ">" "git clone"
        if git clone "https://github.com/$NIXOS_REPO.git" "$REPO_TMP"; then
            log_exec "git" "<" "git clone"
            # _base.toml의 git.nixosRepo와 비교하여 불일치 시 치환 여부 확인
            local _toml_repo _replace
            _toml_repo=$(python3 "$SCRIPT_DIR/nixstrap.lib-repo.py" check-repo "$REPO_TMP")
            if [ -n "$_toml_repo" ] && [ "$_toml_repo" != "$NIXOS_REPO" ]; then
                log_msg "Notice" "_base.toml has git.nixosRepo = '$_toml_repo'"
                read -rp "$(log_prompt)update to '${NIXOS_REPO}'? (Y/n): " _replace
                _replace="${_replace:-Y}"
                if [[ "$_replace" =~ ^[Yy]$ ]]; then
                    python3 "$SCRIPT_DIR/nixstrap.lib-repo.py" update-repo "$REPO_TMP" "$NIXOS_REPO"
                    log_msg "Config" "_base.toml updated: git.nixosRepo = '$NIXOS_REPO'"
                fi
            fi
            break
        else
            log_msg "Error" "clone failed. check the address and try again."
            NIXOS_REPO=""
        fi
    done
}

select_host() {
    local host_data
    host_data=$(python3 "$SCRIPT_DIR/nixstrap.lib-repo.py" list-hosts "$REPO_TMP")

    local -a _host_names=() _host_labels=()
    while IFS='|' read -r _name _type _preset_val; do
        [ -z "$_name" ] && continue
        _host_names+=("$_name")
        _host_labels+=("$(printf "%-24s [%-7s] %s" "$_name" "$_type" "$_preset_val")")
    done <<< "$host_data"

    local -a _all_labels
    if [ ${#_host_labels[@]} -gt 0 ]; then
        _all_labels=("${_host_labels[@]}" "+ Enter new hostname")
    else
        _all_labels=("+ Enter new hostname")
    fi

    echo ""
    _pick "select host (up/down arrow, Enter to confirm):" "${_all_labels[@]}"
    local _sel=$REPLY

    if [ "$_sel" -eq "${#_host_names[@]}" ]; then
        _HOST_IS_NEW=true
        _HOST_TYPE=""
        _HOST_PRESET_FROM_REPO=""
        _HOST_USERNAME=""
        local _hinput
        read -rp "$(log_prompt)new hostname: " _hinput
        HOST="${_hinput:-}"
        if [ -z "$HOST" ]; then
            log_msg "Error" "hostname cannot be empty."
            select_host
            return
        fi
        ask_host_username
    else
        _HOST_IS_NEW=false
        _HOST_USERNAME=""
        HOST="${_host_names[$_sel]}"
        _HOST_TYPE=$(echo "$host_data" | grep "^${HOST}|" | cut -d'|' -f2)
        _HOST_PRESET_FROM_REPO=$(echo "$host_data" | grep "^${HOST}|" | cut -d'|' -f3)
        _PRESET="$_HOST_PRESET_FROM_REPO"
    fi
}

ask_host_username() {
    local _base_user _input
    _base_user=$(python3 "$SCRIPT_DIR/nixstrap.lib-repo.py" username "$REPO_TMP" 2>/dev/null || true)
    read -rp "$(log_prompt)username [${_base_user:-_base.toml}]: " _input
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
    echo ""
    _pick "select preset:" "${_preset_opts[@]}"
    _PRESET="${_preset_opts[$REPLY]}"
}

ask_state_version() {
    local _input
    echo ""
    log_msg "Notice" "pin to a NixOS release? (e.g. 25.11 — leave blank for rolling):"
    read -rp "$(log_prompt)stateVersion: " _input
    _STATE_VERSION="${_input:-}"
    if [ -n "$_STATE_VERSION" ]; then
        log_msg "Config" "stateVersion: $_STATE_VERSION (stable lock)"
    else
        log_msg "Config" "stateVersion: (none — rolling)"
    fi
}

ask_password() {
    local _preview_user _pw _pw2
    _preview_user=$(python3 "$SCRIPT_DIR/nixstrap.lib-repo.py" username "$REPO_TMP" 2>/dev/null || true)
    local _label="${_preview_user:-user}"
    echo ""
    log_msg "Notice" "set login password for '$_label' (press Enter twice to skip):"
    while true; do
        read -rsp "$(log_prompt)password: " _pw
        echo ""
        if [ -z "$_pw" ]; then
            read -rp "$(log_prompt)skip password setup? (y/N): " _skip
            if [[ "${_skip:-N}" =~ ^[Yy]$ ]]; then
                _USER_PASSWORD=""
                log_msg "Notice" "skipped — no password will be set."
                break
            fi
            continue
        fi
        read -rsp "$(log_prompt)confirm:  " _pw2
        echo ""
        if [ "$_pw" = "$_pw2" ]; then
            _USER_PASSWORD="$_pw"
            log_msg "Config" "password accepted."
            break
        fi
        log_msg "Error" "passwords do not match. try again."
    done
}

# ── 세션 관리 ──────────────────────────────────────────────────────────────────

show_summary() {
    local _fmt_boot _fmt_root
    echo ""
    printf "${PURPLE}NIXSTRAP${NC} ${CYAN}%-9s${NC} | Installation configuration:\n" "Review"
    printf "  1. %-11s:  %s\n" "Repository" "${NIXOS_REPO:-(not set)}"

    if [ -n "${HOST:-}" ]; then
        if [ "$_HOST_IS_NEW" = true ]; then
            if [ "$_IS_VM" = true ]; then
                printf "  2. %-11s:  %s  (new, VM: incus-guest=on incus=off)\n" "Hostname" "$HOST"
            else
                printf "  2. %-11s:  %s  (new)\n" "Hostname" "$HOST"
            fi
            local _uname_display="${_HOST_USERNAME:-from _base.toml}"
            printf "     %-11s   username: %s\n" "" "$_uname_display"
        else
            printf "  2. %-11s:  %s  [%s] %s\n" "Hostname" "$HOST" "${_HOST_TYPE:-?}" "${_HOST_PRESET_FROM_REPO:-?}"
            if [ "$_IS_VM" = true ]; then
                printf "     %-11s   VM detected — host.toml already exists, incus settings unchanged\n" ""
            fi
        fi
    else
        printf "  2. %-11s:  %s\n" "Hostname" "(not set)"
    fi

    if [[ "${_PART_MODE:-}" == "1" ]]; then
        _fmt_boot="no"; [[ "${FORMAT_BOOT:-}" =~ ^[Yy]$ ]] && _fmt_boot="yes"
        _fmt_root="no"; [[ "${FORMAT_ROOT:-}" =~ ^[Yy]$ ]] && _fmt_root="yes"
        printf "  3. %-11s:  existing  boot=%s  root=%s\n" \
            "Partitions" "${BOOT_PART:-(not set)}" "${ROOT_PART:-(not set)}"
        printf "     %-11s   format boot: %s  format root: %s\n" "" "$_fmt_boot" "$_fmt_root"
    elif [[ "${_PART_MODE:-}" == "2" ]]; then
        printf "  3. %-11s:  new  %s -> %s (EFI %s), %s (root)\n" \
            "Partitions" "${_DISK:-(not set)}" \
            "${BOOT_PART:-(not set)}" "${_BOOT_SIZE:-?}" "${ROOT_PART:-(not set)}"
        if [[ "${_WIPE:-false}" == "true" ]]; then
            printf "     %-11s   ${RED}WIPE ENTIRE DISK${NC}\n" ""
        fi
    else
        printf "  3. %-11s:  %s\n" "Partitions" "(not set)"
    fi

    if [ "$_HOST_IS_NEW" = true ]; then
        local _sv_display="${_STATE_VERSION:-rolling}"
        printf "  4. %-11s:  %s  (stateVersion: %s)\n" "Preset" "${_PRESET:-workstation}" "$_sv_display"
    else
        printf "  4. %-11s:  %s  (from repo)\n" "Preset" "${_HOST_PRESET_FROM_REPO:-?}"
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
    log_msg "Config" "session saved: $PARAMS_FILE"
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

    log_msg "Notice" "previous session found:"
    printf "     repo=%-30s host=%s\n" "$_repo" "$_host"
    printf "     mode=%-5s boot=%-20s root=%s\n" "$_mode" "$_boot" "$_root"

    _pick "load previous session?" \
        "Yes — load and review" \
        "No  — start fresh (delete saved session)"

    if [ "$REPLY" -eq 0 ]; then
        # shellcheck disable=SC1090
        source "$PARAMS_FILE"
        log_msg "Config" "session loaded."
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
        read -rp "$(log_prompt)Enter=install  1-4=edit  s=save  q=quit: " _review || {
            # Ctrl+C 인터럽트: _trap_int가 경고 처리함. 타임아웃 리셋 없이 루프 재진입.
            _review=""
            continue
        }
        _TRAP_INT_WARNED_AT=0  # 정상 입력 성공 → 타임아웃 리셋 (다음 Ctrl+C는 다시 경고)
        case "${_review:-}" in
            "")
                if [ -z "${HOST:-}" ]; then
                    log_msg "Error" "hostname is required. edit item 2."
                    continue
                fi
                if [ -z "${BOOT_PART:-}" ] || [ -z "${ROOT_PART:-}" ]; then
                    log_msg "Error" "partition info is incomplete. edit item 3."
                    continue
                fi
                save_params
                break
                ;;
            s|S)
                if [ -z "${HOST:-}" ]; then
                    log_msg "Error" "hostname is required. edit item 2."
                    continue
                fi
                if [ -z "${BOOT_PART:-}" ] || [ -z "${ROOT_PART:-}" ]; then
                    log_msg "Error" "partition info is incomplete. edit item 3."
                    continue
                fi
                save_params
                log_msg "Done" "params saved to $PARAMS_FILE. run again to install."
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
                    log_msg "Notice" "preset is fixed for existing hosts (from repo)."
                fi
                ;;
            q|Q) log_msg "Error" "cancelled."; exit 1 ;;
            *) log_msg "Notice" "enter 1-4 to edit, s to save, or press Enter to install." ;;
        esac
    done
}
