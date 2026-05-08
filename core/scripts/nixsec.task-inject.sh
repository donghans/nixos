#!/usr/bin/env bash
# nixsec.task-inject.sh — 원격 주입 / 워크스테이션 로컬 적용 / age 키 복구

# secrets.json 보유 호스트 목록 수집
_collect_secret_hosts() {
    find "$NIXOS_PATH/hosts/deploy" -name "secrets.json" -type f | \
        sed 's|.*/\(.*\)\.secrets/secrets\.json|\1|' | sort
}

# resolved.json 또는 bootstrap.env에서 SSH 접속 정보 조회
# $1=hostname → _INJ_IP, _INJ_SSH_KEY, _INJ_SSH_USER 설정
_resolve_ssh_info() {
    local hostname="$1"
    local resolved_json="$JSON_DIR/resolved.json"

    _INJ_IP="" _INJ_SSH_KEY="" _INJ_SSH_USER=""

    # resolved.json에서 deploy 정보 조회
    if [ -f "$resolved_json" ]; then
        local _deploy
        _deploy=$(jq -r --arg h "$hostname" '.[$h].deploy // empty' "$resolved_json" 2>/dev/null || true)
        if [ -n "$_deploy" ] && [ "$_deploy" != "null" ]; then
            _INJ_IP=$(printf '%s' "$_deploy" | jq -r '.ip // empty')
            _INJ_SSH_KEY=$(printf '%s' "$_deploy" | jq -r '.sshKey // empty')
            _INJ_SSH_KEY="${_INJ_SSH_KEY/#\~/$HOME}"
            _INJ_SSH_USER=$(jq -r --arg h "$hostname" '.[$h].username // "root"' "$resolved_json" 2>/dev/null)
            return
        fi
    fi

    # standalone: bootstrap.env에서 조회
    local _env="$HOME/.ssh/rnixup/${hostname}.bootstrap.env"
    if [ -f "$_env" ]; then
        # shellcheck disable=SC1090
        source "$_env"
        _INJ_IP="${_BOOTSTRAP_IP:-}"
        _INJ_SSH_KEY="${_BOOTSTRAP_SSH_KEY:-}"
        _INJ_SSH_USER="${_BOOTSTRAP_SSH_USER:-root}"
    fi
}

_run_remote_inject() {
    log_msg "Task" "원격 호스트에 시크릿 주입"
    printf '\n'

    # 대상 호스트 선택
    local -a _hosts=()
    mapfile -t _hosts < <(_collect_secret_hosts)

    local _hostname=""
    local -a _host_labels=("${_hosts[@]}" "직접 입력")
    _pick "대상 호스트 선택:" "${_host_labels[@]}"
    if [ "$REPLY" -ge "${#_hosts[@]}" ]; then
        log_msg "Input" "호스트명: "
        read -re _hostname
    else
        _hostname="${_hosts[$REPLY]}"
    fi

    # SSH 접속 정보 확인
    _resolve_ssh_info "$_hostname"

    if [ -z "$_INJ_IP" ]; then
        log_msg "Input" "IP 또는 호스트명: "
        read -re _INJ_IP
    else
        log_msg "Notice" "IP: $_INJ_IP (자동 조회)"
    fi

    if [ -z "$_INJ_SSH_KEY" ]; then
        log_msg "Input" "SSH 키 파일 경로 (Tab 완성): "
        read -re _INJ_SSH_KEY
        _INJ_SSH_KEY="${_INJ_SSH_KEY/#\~/$HOME}"
    else
        log_msg "Notice" "SSH 키: $_INJ_SSH_KEY (자동 조회)"
    fi

    _INJ_SSH_USER="${_INJ_SSH_USER:-root}"

    local ssh_opts=(
        -o StrictHostKeyChecking=yes
        -o BatchMode=yes
        -o UserKnownHostsFile="$HOME/.ssh/known_hosts"
        -o LogLevel=ERROR
    )

    # lib-secrets.sh 로드 (inject_secrets 사용)
    local _lib="$SCRIPT_DIR/rnixup.lib-secrets.sh"
    [ -f "$_lib" ] || { log_msg "Error" "rnixup.lib-secrets.sh 없음"; exit 1; }
    source "$_lib"

    inject_secrets "$_hostname" "$_INJ_SSH_USER" "$_INJ_IP" "$_INJ_SSH_KEY" "${ssh_opts[@]}"
}

_run_local_apply() {
    log_msg "Task" "이 워크스테이션에 시크릿 적용"
    printf '\n'

    # 현재 호스트명으로 secrets.json 탐색
    local _cur_host
    _cur_host=$(hostname -s)
    local _config_file="$NIXOS_PATH/hosts/deploy/${_cur_host}.secrets/secrets.json"

    if [ ! -f "$_config_file" ]; then
        log_msg "Notice" "현재 호스트($_cur_host)의 secrets.json이 없습니다."
        log_msg "Input" "호스트명 직접 입력: "
        read -re _cur_host
        _config_file="$NIXOS_PATH/hosts/deploy/${_cur_host}.secrets/secrets.json"
        [ -f "$_config_file" ] || { log_msg "Error" "secrets.json 없음: $_config_file"; exit 1; }
    else
        log_msg "Notice" "호스트: $_cur_host"
    fi

    local _config
    _config=$(cat "$_config_file")

    # 그룹 선택
    local -a _groups=()
    mapfile -t _groups < <(printf '%s' "$_config" | jq -r '.groups | keys[]')

    local -a _check_args=()
    for _g in "${_groups[@]}"; do
        local _repo _cnt
        _repo=$(printf '%s' "$_config" | jq -r --arg g "$_g" '.groups[$g].repo')
        _cnt=$(printf '%s' "$_config" | jq -r --arg g "$_g" '.groups[$g].secrets | length')
        _check_args+=("$_g" "${_g}  (${_cnt}개 시크릿, ${_repo})")
    done

    _check "적용할 그룹 선택  기본=건너뜀" "${_check_args[@]}"
    [ "${#REPLY_CHECKED[@]}" -eq 0 ] && { log_msg "Notice" "선택 없음, 종료."; return; }

    # lib-secrets.sh에서 _resolve_age_key_for_repo 재사용
    source "$SCRIPT_DIR/rnixup.lib-secrets.sh"

    for _g in "${REPLY_CHECKED[@]}"; do
        local _repo
        _repo=$(printf '%s' "$_config" | jq -r --arg g "$_g" '.groups[$g].repo')
        _resolve_age_key_for_repo "$_repo"

        while IFS=$'\t' read -r _remote _server; do
            # home/ 접두사 처리
            local _dest
            if [[ "$_server" == home/* ]]; then
                _dest="$HOME/${_server#home/}"
            else
                _dest="/$_server"
            fi
            mkdir -p "$(dirname "$_dest")"

            log_msg "Task" "[$_g] 복호화: $_remote → $_dest"
            gh api "repos/$_repo/contents/${_remote}.age" --jq '.content' \
                | base64 -d \
                | age -d -i "$REPLY_AGE_KEY" \
                > "$_dest"

            # 시스템 경로는 sudo로 권한 설정
            if [[ "$_dest" == /var/* ]] || [[ "$_dest" == /etc/* ]]; then
                sudo chmod 600 "$_dest"
            else
                chmod 600 "$_dest"
            fi
            log_msg "Done" "적용: $_dest"
        done < <(printf '%s' "$_config" | jq -r --arg g "$_g" \
            '.groups[$g].secrets | to_entries[] | [.key, .value] | @tsv')
    done
}

_run_key_restore() {
    log_msg "Task" "age 키 경로 복구"
    printf '\n'

    # 레포 선택
    local -a _repos=()
    mapfile -t _repos < <(
        find "$NIXOS_PATH/hosts/deploy" -name "secrets.json" | \
        xargs jq -r '.groups[].repo' 2>/dev/null | sort -u
    )

    local _repo=""
    if [ "${#_repos[@]}" -gt 0 ]; then
        local -a _labels=("${_repos[@]}" "직접 입력")
        _pick "레포 선택:" "${_labels[@]}"
        if [ "$REPLY" -ge "${#_repos[@]}" ]; then
            log_msg "Input" "레포 이름 (예: owner/nix-secrets): "
            read -re _repo
        else
            _repo="${_repos[$REPLY]}"
        fi
    else
        log_msg "Input" "레포 이름 (예: owner/nix-secrets): "
        read -re _repo
    fi

    printf '\n'
    log_msg "Input" "Google Drive에서 내려받은 age 키 파일 경로 (Tab 완성):"
    local _key_path
    read -re _key_path
    _key_path="${_key_path/#\~/$HOME}"
    [ -f "$_key_path" ] || { log_msg "Error" "파일 없음: $_key_path"; exit 1; }

    local _slug="${_repo//\//-}"
    local _cache="$HOME/.cache/nix-secrets/${_slug}.key-path"
    mkdir -p "$(dirname "$_cache")"
    printf '%s' "$_key_path" > "$_cache"

    log_msg "Done" "캐시됨: $_cache"
    log_msg "Notice" "이제 rnixstrap/rnixup/nixsec에서 자동으로 이 키를 사용합니다."
}
