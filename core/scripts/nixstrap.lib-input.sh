#!/usr/bin/env bash
# nixstrap.lib-input.sh — Phase 1 대화형 질문 함수

ask_repo_and_clone() {
    local _prompt _input
    while true; do
        if [ -n "${NIXOS_REPO:-}" ]; then
            _prompt="$(printf "$(log_prompt)repository [%s]: " "$NIXOS_REPO")"
        else
            _prompt="$(printf "$(log_prompt)repository (e.g. user/nixos): ")"
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
            # base.toml의 git.nixosRepo와 비교하여 불일치 시 치환 여부 확인
            local _toml_repo _replace
            _toml_repo=$(python3 "$SCRIPT_DIR/nixstrap.repo.py" check-repo "$REPO_TMP")
            if [ -n "$_toml_repo" ] && [ "$_toml_repo" != "$NIXOS_REPO" ]; then
                log_msg "Notice" "base.toml has git.nixosRepo = '$_toml_repo'"
                read -rp "$(printf "$(log_prompt)update to '$NIXOS_REPO'? (Y/n): ")" _replace
                _replace="${_replace:-Y}"
                if [[ "$_replace" =~ ^[Yy]$ ]]; then
                    python3 "$SCRIPT_DIR/nixstrap.repo.py" update-repo "$REPO_TMP" "$NIXOS_REPO"
                    log_msg "Config" "base.toml updated: git.nixosRepo = '$NIXOS_REPO'"
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
    host_data=$(python3 "$SCRIPT_DIR/nixstrap.repo.py" list-hosts "$REPO_TMP")

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
        local _hinput
        read -rp "$(printf "$(log_prompt)new hostname: ")" _hinput
        HOST="${_hinput:-}"
        if [ -z "$HOST" ]; then
            log_msg "Error" "hostname cannot be empty."
            select_host
            return
        fi
    else
        _HOST_IS_NEW=false
        HOST="${_host_names[$_sel]}"
        _HOST_TYPE=$(echo "$host_data" | grep "^${HOST}|" | cut -d'|' -f2)
        _HOST_PRESET_FROM_REPO=$(echo "$host_data" | grep "^${HOST}|" | cut -d'|' -f3)
        _PRESET="$_HOST_PRESET_FROM_REPO"
    fi
}

ask_partitions() {
    local _USE_WHOLE _CONFIRM_WIPE _FREE_OUTPUT _FREE_SEL _SELECTED
    local _NUM _FS _FE _FSZ _OLD_PART_COUNT

    echo ""
    log_msg "Disk" "current block devices:"
    lsblk -o NAME,SIZE,TYPE,FSTYPE,LABEL,MOUNTPOINT
    echo ""

    # 재진입마다 파티션 상태 초기화 (review_loop에서 재편집 지원)
    _NEW_PARTITIONS=false
    BOOT_PART=""
    ROOT_PART=""
    FORMAT_BOOT=""
    FORMAT_ROOT=""
    _WIPE=false

    while true; do
        read -rp "$(printf "$(log_prompt)partition mode — 1=use existing, 2=create new [2]: ")" _PART_MODE
        _PART_MODE="${_PART_MODE:-2}"
        [[ "$_PART_MODE" == "1" || "$_PART_MODE" == "2" ]] && break
        log_msg "Error" "invalid mode. select 1 or 2."
    done

    if [[ "$_PART_MODE" == "1" ]]; then
        # EFI 파티션 선택
        local _efi_data _efi_name _efi_size _efi_fs _efi_label
        local -a _efi_paths=() _efi_labels=()
        _efi_data=$(python3 "$SCRIPT_DIR/nixstrap.part.py" list-parts efi)
        if [[ "$_efi_data" != "NONE" ]]; then
            while IFS='|' read -r _efi_name _efi_size _efi_fs _efi_label; do
                [ -z "$_efi_name" ] && continue
                _efi_paths+=("/dev/$_efi_name")
                _efi_labels+=("$(printf "%-16s %8s  %s" "$_efi_name" "$_efi_size" "${_efi_label:-<unlabeled>}")")
            done <<< "$_efi_data"
        fi
        _efi_labels+=("+ Enter manually")

        echo ""
        _pick "select EFI partition:" "${_efi_labels[@]}"
        if [ "$REPLY" -eq "${#_efi_paths[@]}" ]; then
            while true; do
                read -rp "$(printf "$(log_prompt)EFI partition path: ")" BOOT_PART
                [ -b "$BOOT_PART" ] && break
                log_msg "Error" "device not found: $BOOT_PART"
            done
        else
            BOOT_PART="${_efi_paths[$REPLY]}"
        fi

        # Root 파티션 선택
        local _root_data _root_name _root_size _root_fs _root_label
        local -a _root_paths=() _root_labels=()
        _root_data=$(python3 "$SCRIPT_DIR/nixstrap.part.py" list-parts root)
        if [[ "$_root_data" != "NONE" ]]; then
            while IFS='|' read -r _root_name _root_size _root_fs _root_label; do
                [ -z "$_root_name" ] && continue
                _root_paths+=("/dev/$_root_name")
                _root_labels+=("$(printf "%-16s %8s [%-5s] %s" "$_root_name" "$_root_size" "$_root_fs" "${_root_label:-<unlabeled>}")")
            done <<< "$_root_data"
        fi
        _root_labels+=("+ Enter manually")

        echo ""
        _pick "select root partition:" "${_root_labels[@]}"
        if [ "$REPLY" -eq "${#_root_paths[@]}" ]; then
            while true; do
                read -rp "$(printf "$(log_prompt)root partition path: ")" ROOT_PART
                [ -b "$ROOT_PART" ] && break
                log_msg "Error" "device not found: $ROOT_PART"
            done
        else
            ROOT_PART="${_root_paths[$REPLY]}"
        fi

        read -rp "$(printf "$(log_prompt)format boot partition ($BOOT_PART)? (y/N): ")" FORMAT_BOOT
        read -rp "$(printf "$(log_prompt)format root partition ($ROOT_PART)? (y/N): ")" FORMAT_ROOT

    else
        # 디스크 선택
        local _disk_data _disk_name _disk_size
        local -a _disk_paths=() _disk_labels=()
        _disk_data=$(python3 "$SCRIPT_DIR/nixstrap.part.py" list-parts disk)
        if [[ "$_disk_data" != "NONE" ]]; then
            while IFS='|' read -r _disk_name _disk_size; do
                [ -z "$_disk_name" ] && continue
                _disk_paths+=("/dev/$_disk_name")
                _disk_labels+=("$(printf "%-16s %8s" "$_disk_name" "$_disk_size")")
            done <<< "$_disk_data"
        fi
        _disk_labels+=("+ Enter manually")

        echo ""
        _pick "select target disk:" "${_disk_labels[@]}"
        if [ "$REPLY" -eq "${#_disk_paths[@]}" ]; then
            while true; do
                read -rp "$(printf "$(log_prompt)target disk path: ")" _DISK
                [ -b "$_DISK" ] && break
                log_msg "Error" "device not found: $_DISK"
            done
        else
            _DISK="${_disk_paths[$REPLY]}"
        fi

        read -rp "$(printf "$(log_prompt)use entire disk? (Y/n): ")" _USE_WHOLE
        _USE_WHOLE="${_USE_WHOLE:-Y}"

        if [[ "$_USE_WHOLE" =~ ^[Yy]$ ]]; then
            read -rp "$(printf "$(log_prompt_danger)WARNING: ALL data on '%s' will be erased. type 'yes' to confirm: " "$_DISK")" _CONFIRM_WIPE
            if [[ "$_CONFIRM_WIPE" != "yes" ]]; then
                log_msg "Error" "cancelled."
                exit 1
            fi
            _PART_START="1MiB"
            _PART_END="100%"
            _WIPE=true
        else
            log_msg "Disk" "scanning free space on $_DISK ..."
            _FREE_OUTPUT=$(python3 "$SCRIPT_DIR/nixstrap.part.py" free-space "$_DISK")

            if [[ "$_FREE_OUTPUT" == "NONE" ]]; then
                log_msg "Error" "no usable free space (>=2GiB) found on $_DISK."
                exit 1
            fi

            echo ""
            log_msg "Disk" "available free space:"
            while IFS=: read -r _NUM _FS _FE _FSZ; do
                printf "  %s) %s ~ %s  (%s)\n" "$_NUM" "$_FS" "$_FE" "$_FSZ"
            done <<< "$_FREE_OUTPUT"
            echo ""

            while true; do
                read -rp "$(printf "$(log_prompt)select number or enter range (e.g. 128GiB-476GiB): ")" _FREE_SEL
                if [[ "$_FREE_SEL" =~ ^[0-9]+$ ]]; then
                    _SELECTED=$(echo "$_FREE_OUTPUT" | grep "^${_FREE_SEL}:" || true)
                    if [ -z "$_SELECTED" ]; then
                        log_msg "Error" "invalid selection."
                        continue
                    fi
                    _PART_START=$(echo "$_SELECTED" | cut -d: -f2)
                    _PART_END=$(echo "$_SELECTED" | cut -d: -f3)
                else
                    _PART_START="${_FREE_SEL%-*}"
                    _PART_END="${_FREE_SEL#*-}"
                    local _range_err
                    if ! _range_err=$(python3 "$SCRIPT_DIR/nixstrap.part.py" check-range "$_PART_START" "$_PART_END" 2>&1); then
                        log_msg "Error" "$_range_err"
                        continue
                    fi
                fi
                break
            done
            _WIPE=false
        fi

        read -rp "$(printf "$(log_prompt)boot partition size (default: 1GiB, enter): ")" _BOOT_SIZE
        _BOOT_SIZE="${_BOOT_SIZE:-1GiB}"

        _BOOT_END=$(python3 "$SCRIPT_DIR/nixstrap.part.py" boot-end "$_PART_START" "$_BOOT_SIZE")

        # 기존 파티션 수로 새 파티션 번호 계산
        _OLD_PART_COUNT=$(parted -m "$_DISK" unit MiB print 2>/dev/null | grep -c '^[0-9]' || echo "0")
        _NEW_BOOT_NUM=$((_OLD_PART_COUNT + 1))
        _NEW_ROOT_NUM=$((_OLD_PART_COUNT + 2))

        # nvme/mmcblk은 숫자로 끝나는 디스크명에 'p' 삽입 필요 (nvme0n1p1 vs sda1)
        if [[ "$_DISK" =~ [0-9]$ ]]; then
            BOOT_PART="${_DISK}p${_NEW_BOOT_NUM}"
            ROOT_PART="${_DISK}p${_NEW_ROOT_NUM}"
        else
            BOOT_PART="${_DISK}${_NEW_BOOT_NUM}"
            ROOT_PART="${_DISK}${_NEW_ROOT_NUM}"
        fi

        _NEW_PARTITIONS=true
        FORMAT_BOOT="y"
        FORMAT_ROOT="y"
    fi
}

ask_preset() {
    # iso.toml 제외 — 설치 컨텍스트에서는 iso 프리셋 사용 불가
    local -a _preset_opts=()
    while IFS= read -r _pname; do
        [ -z "$_pname" ] && continue
        _preset_opts+=("$_pname")
    done < <(python3 "$SCRIPT_DIR/nixstrap.repo.py" list-presets "$REPO_TMP")

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
    read -rp "$(printf "$(log_prompt)stateVersion: ")" _input
    _STATE_VERSION="${_input:-}"
    if [ -n "$_STATE_VERSION" ]; then
        log_msg "Config" "stateVersion: $_STATE_VERSION (stable lock)"
    else
        log_msg "Config" "stateVersion: (none — rolling)"
    fi
}

ask_password() {
    local _preview_user _pw _pw2
    _preview_user=$(python3 "$SCRIPT_DIR/nixstrap.repo.py" username "$REPO_TMP" 2>/dev/null || true)
    local _label="${_preview_user:-user}"
    echo ""
    log_msg "Notice" "set login password for '$_label' (press Enter twice to skip):"
    while true; do
        read -rsp "$(printf "$(log_prompt)password: ")" _pw
        echo ""
        if [ -z "$_pw" ]; then
            read -rp "$(printf "$(log_prompt)skip password setup? (y/N): ")" _skip
            if [[ "${_skip:-N}" =~ ^[Yy]$ ]]; then
                _USER_PASSWORD=""
                log_msg "Notice" "skipped — no password will be set."
                break
            fi
            continue
        fi
        read -rsp "$(printf "$(log_prompt)confirm:  ")" _pw2
        echo ""
        if [ "$_pw" = "$_pw2" ]; then
            _USER_PASSWORD="$_pw"
            log_msg "Config" "password accepted."
            break
        fi
        log_msg "Error" "passwords do not match. try again."
    done
}

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
        read -rp "$(printf "$(log_prompt)Enter=proceed  1-4=edit  q=quit: ")" _review
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
            *) log_msg "Notice" "enter 1-4 to edit an item, or press Enter to proceed." ;;
        esac
    done
}
