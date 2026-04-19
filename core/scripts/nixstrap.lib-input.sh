#!/usr/bin/env bash
# nixstrap.lib-input.sh — Phase 1 대화형 입력 함수 (레포·호스트·프리셋·패스워드)

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
