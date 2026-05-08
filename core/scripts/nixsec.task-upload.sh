#!/usr/bin/env bash
# nixsec.task-upload.sh — 시크릿 암호화 + GitHub 레포에 업로드

# 사용 가능한 레포 목록 수집 (secrets.json에서)
_collect_repos() {
    find "$NIXOS_PATH/hosts/deploy" -name "secrets.json" -type f \
        | xargs jq -r '.groups[].repo' 2>/dev/null \
        | sort -u
}

# 레포의 .pubkey를 gh api로 가져옴
_get_repo_pubkey() {
    local repo="$1"
    gh api "repos/$repo/contents/.pubkey" --jq '.content' | base64 -d | tr -d '\n'
}

# 파일을 age 암호화 후 gh api로 업로드 (create or update)
_upload_encrypted() {
    local repo="$1" remote_path="$2" local_file="$3" pubkey="$4"

    log_msg "Task" "암호화 중: $(basename "$local_file")"
    local _encrypted
    _encrypted=$(age -r "$pubkey" < "$local_file" | base64 | tr -d '\n')

    local _api_path="repos/$repo/contents/${remote_path}.age"
    local _sha=""
    _sha=$(gh api "$_api_path" --jq '.sha' 2>/dev/null || true)

    local _message="update: $remote_path"
    [ -z "$_sha" ] && _message="add: $remote_path"

    if [ -n "$_sha" ]; then
        gh api "$_api_path" -X PUT \
            -f message="$_message" \
            -f content="$_encrypted" \
            -f sha="$_sha" &>/dev/null
    else
        gh api "$_api_path" -X PUT \
            -f message="$_message" \
            -f content="$_encrypted" &>/dev/null
    fi

    log_msg "Done" "업로드 완료: ${remote_path}.age"
}

_run_upload() {
    log_msg "Task" "시크릿 업로드"
    printf '\n'

    # 레포 선택
    local -a _repos=()
    mapfile -t _repos < <(_collect_repos)
    local _repo=""

    if [ "${#_repos[@]}" -eq 0 ]; then
        log_msg "Notice" "secrets.json에서 레포를 찾을 수 없습니다. 직접 입력합니다."
        log_msg "Input" "레포 이름 (예: owner/nix-secrets): "
        read -re _repo
    else
        local -a _repo_labels=("${_repos[@]}" "직접 입력")
        _pick "레포 선택:" "${_repo_labels[@]}"
        if [ "$REPLY" -ge "${#_repos[@]}" ]; then
            log_msg "Input" "레포 이름: "
            read -re _repo
        else
            _repo="${_repos[$REPLY]}"
        fi
    fi

    # 그룹 선택
    local -a _groups=()
    mapfile -t _groups < <(
        find "$NIXOS_PATH/hosts/deploy" -name "secrets.json" | \
        xargs jq -r --arg r "$_repo" \
            'if .groups then .groups | to_entries[] | select(.value.repo == $r) | .key else empty end' \
            2>/dev/null | sort -u
    )

    local _group=""
    local -a _group_labels=()
    for g in "${_groups[@]}"; do _group_labels+=("$g"); done
    _group_labels+=("새 그룹명 직접 입력")

    _pick "그룹 선택:" "${_group_labels[@]}"
    if [ "$REPLY" -ge "${#_groups[@]}" ]; then
        log_msg "Input" "그룹명: "
        read -re _group
    else
        _group="${_groups[$REPLY]}"
    fi

    # 시크릿 경로 선택
    local -a _existing_secrets=()
    mapfile -t _existing_secrets < <(
        find "$NIXOS_PATH/hosts/deploy" -name "secrets.json" | \
        xargs jq -r --arg r "$_repo" --arg g "$_group" \
            'if .groups[$g] and .groups[$g].repo == $r then .groups[$g].secrets | keys[] else empty end' \
            2>/dev/null | sort -u
    )

    local _remote_path=""
    if [ "${#_existing_secrets[@]}" -gt 0 ]; then
        local -a _secret_labels=("${_existing_secrets[@]}" "새 경로 직접 입력")
        _pick "업로드할 시크릿 경로 선택:" "${_secret_labels[@]}"
        if [ "$REPLY" -ge "${#_existing_secrets[@]}" ]; then
            log_msg "Input" "레포 내 경로 (예: hostname/group/secret-name): "
            read -re _remote_path
        else
            _remote_path="${_existing_secrets[$REPLY]}"
        fi
    else
        log_msg "Input" "레포 내 경로 (예: hostname/group/secret-name): "
        read -re _remote_path
    fi

    # 소스 선택
    printf '\n'
    _pick "시크릿 소스 선택:" \
        "로컬 파일     — 파일 경로 입력" \
        "직접 입력     — 텍스트로 입력 (echo 없음)" \
        "AWS SSM      — Parameter Store에서 가져오기"

    local _tmp_file
    _tmp_file=$(mktemp)
    chmod 600 "$_tmp_file"
    # shellcheck disable=SC2064
    trap "rm -f '$_tmp_file'" RETURN

    case "$REPLY" in
        0)
            log_msg "Input" "파일 경로 (Tab 완성): "
            local _local_file
            read -re _local_file
            _local_file="${_local_file/#\~/$HOME}"
            [ -f "$_local_file" ] || { log_msg "Error" "파일 없음: $_local_file"; exit 1; }
            cp "$_local_file" "$_tmp_file"
            ;;
        1)
            log_msg "Input" "내용 입력 (입력 후 Enter, Ctrl-D로 완료):"
            cat > "$_tmp_file"
            ;;
        2)
            command -v aws &>/dev/null || { log_msg "Error" "aws CLI가 필요합니다."; exit 1; }
            log_msg "Input" "SSM 파라미터 경로 (예: /nix-secrets/step-ca/key): "
            local _ssm_path
            read -re _ssm_path
            log_msg "Task" "SSM에서 가져오는 중..."
            aws ssm get-parameter \
                --name "$_ssm_path" \
                --with-decryption \
                --query "Parameter.Value" \
                --output text > "$_tmp_file"
            ;;
    esac

    # pubkey 가져오기
    printf '\n'
    log_msg "Task" "레포 공개키 조회 중..."
    local _pubkey
    _pubkey=$(_get_repo_pubkey "$_repo") || {
        log_msg "Error" ".pubkey 조회 실패. nixsec 초기화가 완료됐는지 확인하세요."; exit 1
    }

    _upload_encrypted "$_repo" "$_remote_path" "$_tmp_file" "$_pubkey"
}
