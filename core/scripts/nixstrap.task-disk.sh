#!/usr/bin/env bash
# nixstrap.task-disk.sh — Phase 1 디스크·파티션 입력 함수
# shellcheck disable=SC2034  # nixstrap.sh와 nixstrap.task-install.sh이 공유하는 전역 상태 변수

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
        read -rp "$(_log_prompt)partition mode — 1=use existing, 2=create new [2]: " _PART_MODE
        _PART_MODE="${_PART_MODE:-2}"
        [[ "$_PART_MODE" == "1" || "$_PART_MODE" == "2" ]] && break
        log_msg "Error" "invalid mode. select 1 or 2."
    done

    if [[ "$_PART_MODE" == "1" ]]; then
        # EFI 파티션 선택
        local _efi_data _efi_name _efi_size _efi_fs _efi_label
        local -a _efi_paths=() _efi_labels=()
        _efi_data=$(python3 "$SCRIPT_DIR/nixstrap.lib-part.py" list-parts efi)
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
                read -rp "$(_log_prompt)EFI partition path: " BOOT_PART
                [ -b "$BOOT_PART" ] && break
                log_msg "Error" "device not found: $BOOT_PART"
            done
        else
            BOOT_PART="${_efi_paths[$REPLY]}"
        fi

        # Root 파티션 선택
        local _root_data _root_name _root_size _root_fs _root_label
        local -a _root_paths=() _root_labels=()
        _root_data=$(python3 "$SCRIPT_DIR/nixstrap.lib-part.py" list-parts root)
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
                read -rp "$(_log_prompt)root partition path: " ROOT_PART
                [ -b "$ROOT_PART" ] && break
                log_msg "Error" "device not found: $ROOT_PART"
            done
        else
            ROOT_PART="${_root_paths[$REPLY]}"
        fi

        read -rp "$(_log_prompt)format boot partition (${BOOT_PART})? (y/N): " FORMAT_BOOT
        read -rp "$(_log_prompt)format root partition (${ROOT_PART})? (y/N): " FORMAT_ROOT

    else
        # 디스크 선택
        local _disk_data _disk_name _disk_size
        local -a _disk_paths=() _disk_labels=()
        _disk_data=$(python3 "$SCRIPT_DIR/nixstrap.lib-part.py" list-parts disk)
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
                read -rp "$(_log_prompt)target disk path: " _DISK
                [ -b "$_DISK" ] && break
                log_msg "Error" "device not found: $_DISK"
            done
        else
            _DISK="${_disk_paths[$REPLY]}"
        fi

        read -rp "$(_log_prompt)use entire disk? (Y/n): " _USE_WHOLE
        _USE_WHOLE="${_USE_WHOLE:-Y}"

        if [[ "$_USE_WHOLE" =~ ^[Yy]$ ]]; then
            read -rp "$(_log_prompt_danger)WARNING: ALL data on '${_DISK}' will be erased. type 'yes' to confirm: " _CONFIRM_WIPE
            if [[ "$_CONFIRM_WIPE" != "yes" ]]; then
                log_msg "Error" "cancelled."
                exit 1
            fi
            _PART_START="1MiB"
            _PART_END="100%"
            _WIPE=true
        else
            log_msg "Disk" "scanning free space on $_DISK ..."
            _FREE_OUTPUT=$(python3 "$SCRIPT_DIR/nixstrap.lib-part.py" free-space "$_DISK")

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
                read -rp "$(_log_prompt)select number or enter range (e.g. 128GiB-476GiB): " _FREE_SEL
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
                    if ! _range_err=$(python3 "$SCRIPT_DIR/nixstrap.lib-part.py" check-range "$_PART_START" "$_PART_END" 2>&1); then
                        log_msg "Error" "$_range_err"
                        continue
                    fi
                fi
                break
            done
            _WIPE=false
        fi

        read -rp "$(_log_prompt)boot partition size (default: 1GiB, enter): " _BOOT_SIZE
        _BOOT_SIZE="${_BOOT_SIZE:-1GiB}"

        _BOOT_END=$(python3 "$SCRIPT_DIR/nixstrap.lib-part.py" boot-end "$_PART_START" "$_BOOT_SIZE")

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
