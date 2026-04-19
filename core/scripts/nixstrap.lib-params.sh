#!/usr/bin/env bash
# nixstrap.lib-params.sh — Phase 1 세션 상태 관리 (저장·불러오기·요약·검토 루프)

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
