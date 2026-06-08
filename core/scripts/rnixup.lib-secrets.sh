#!/usr/bin/env bash
# rnixup.lib-secrets.sh — secrets.json 기반 시크릿 fetch + 원격 주입
#
# 공개 인터페이스:
#   inject_secrets <hostname> <ssh_user> <ip> <ssh_key> [ssh_opts...]
#   inject_all_remote_secrets          (rnixup용 — resolved.json 기반)
#   _any_remote_secrets_exist          (rnixup용 — secrets.json 유무 확인)
#
# secrets.json 포맷 (hosts/_deploy/<hostname>.secrets/secrets.json):
#   {
#     "appId": "1234567",               ← GitHub App ID (옵션, GitHub Apps 인증 시)
#     "groups": {
#       "<group>": {
#         "repo": "owner/nix-secrets",
#         "installationId": "9876543",  ← GitHub App Installation ID (옵션)
#         "secrets": { "<레포 내 경로>": "<서버 상대 경로>", ... }
#       }
#     }
#   }
#
# 보안 원칙: age 복호화는 항상 워크스테이션에서 수행, 복호화된 파일만 SSH 전송

# SSH 비밀번호 인증 (비어있으면 키 인증 사용)
# 호출자가 설정: _SECRETS_SSH_PASS="<password>"
_SECRETS_SSH_PASS=""

# secrets.json 내용 반환. 없으면 return 1
_get_secrets_config() {
    local hostname="$1"
    local f="$NIXOS_PATH/hosts/_deploy/${hostname}.secrets/secrets.json"
    [ -f "$f" ] || return 1
    cat "$f"
}

# resolved.json의 deploy 호스트 중 실제 주입 가능한 항목(groups 또는 from-new.sh)이 있으면 true
_any_remote_secrets_exist() {
    local resolved_json="$JSON_DIR/resolved.json"
    local hostname
    while IFS= read -r hostname; do
        [ -n "${DEPLOY_NODE:-}" ] && [ "$hostname" != "$DEPLOY_NODE" ] && continue
        local config
        config=$(_get_secrets_config "$hostname") || continue
        local group_count
        group_count=$(printf '%s' "$config" | jq -r '(.groups // {}) | length' 2>/dev/null) || continue
        [ "${group_count:-0}" -gt 0 ] && return 0
        local secrets_dir="$NIXOS_PATH/hosts/_deploy/${hostname}.secrets"
        find "$secrets_dir" -name "from-new.sh" -type f 2>/dev/null | grep -q . && return 0
    done < <(jq -r 'to_entries[] | select(.value.deploy != null) | .key' "$resolved_json")
    return 1
}

# age 키 경로 해석 (캐시 우선, 없으면 대화형 입력 후 캐싱)
# $1 = repo (owner/name)  → REPLY_AGE_KEY 설정
_resolve_age_key_for_repo() {
    local repo="$1"
    local slug="${repo//\//-}"
    local cache="$HOME/.cache/nix-secrets/${slug}.key-path"
    local key_path=""

    [ -f "$cache" ] && key_path=$(cat "$cache")

    if [ ! -f "${key_path:-}" ]; then
        printf '\n'
        log_msg "Input" "[$repo] age 키가 필요합니다."
        printf '  Google Drive에서 nix-secrets.age.key를 내려받은 후 경로를 입력하세요.\n'
        printf '  파일 경로 (Tab 완성): '
        read -re key_path < /dev/tty
        key_path="${key_path/#\~/$HOME}"
        [ -f "$key_path" ] || { log_msg "Error" "파일 없음: $key_path"; exit 1; }
        mkdir -p "$(dirname "$cache")"
        printf '%s' "$key_path" > "$cache"
        log_msg "Notice" "경로 캐시됨 → 다음 실행부터 자동 사용"
    fi

    REPLY_AGE_KEY="$key_path"
}

# GitHub Apps PEM 경로 캐싱 (age 키 패턴과 동일)
# 캐시: ~/.cache/nix-secrets/github-apps.pem-path  →  REPLY_GITHUB_APPS_PEM 설정
_resolve_github_apps_pem() {
    local cache="$HOME/.cache/nix-secrets/github-apps.pem-path"
    local pem_path=""
    [ -f "$cache" ] && pem_path=$(cat "$cache")
    if [ ! -f "${pem_path:-}" ]; then
        printf '\n'
        log_msg "Input" "GitHub Apps 개인키 (PEM) 경로를 입력하세요."
        printf '  파일 경로 (Tab 완성): '
        read -re pem_path < /dev/tty
        pem_path="${pem_path/#\~/$HOME}"
        [ -f "$pem_path" ] || { log_msg "Error" "파일 없음: $pem_path"; exit 1; }
        mkdir -p "$(dirname "$cache")"
        printf '%s' "$pem_path" > "$cache"
        log_msg "Notice" "PEM 경로 캐싱됨 → 다음 실행부터 자동 사용"
    fi
    REPLY_GITHUB_APPS_PEM="$pem_path"
}

# GitHub Apps installation token 발급 (RS256 JWT → access token)
# hosts/_lib/headscale-db-backup.nix getTokenScript 이식
# $1=app_id  $2=installation_id  $3=pem_file → stdout: token
_github_apps_token() {
    local app_id="$1" installation_id="$2" pem_file="$3"
    local now header payload sig jwt token
    now=$(date +%s)
    header=$(printf '{"alg":"RS256","typ":"JWT"}' | base64 -w0 | tr '+/' '-_' | tr -d '=')
    payload=$(printf '{"iat":%s,"exp":%s,"iss":"%s"}' "$((now - 60))" "$((now + 540))" "$app_id" \
        | base64 -w0 | tr '+/' '-_' | tr -d '=')
    sig=$(printf '%s.%s' "$header" "$payload" \
        | openssl dgst -binary -sha256 -sign "$pem_file" \
        | base64 -w0 | tr '+/' '-_' | tr -d '=')
    jwt="$header.$payload.$sig"
    token=$(curl -sf -X POST \
        -H "Accept: application/vnd.github+json" \
        -H "Authorization: Bearer $jwt" \
        "https://api.github.com/app/installations/$installation_id/access_tokens" \
        | jq -r '.token')
    printf '%s' "$token"
}

# GitHub API curl 래퍼 (gh api 대체)
# $1=token  $2=method(GET/PUT)  $3=path(repos/...)  $4=json_body(선택, PUT용)
_gh_curl() {
    local token="$1" method="${2:-GET}" path="$3" body="${4:-}"
    local args=(-sf -X "$method"
        -H "Authorization: Bearer $token"
        -H "Accept: application/vnd.github+json"
        "https://api.github.com/$path")
    [ -n "$body" ] && args+=(-H "Content-Type: application/json" -d "$body")
    curl "${args[@]}"
}

# 그룹의 시크릿을 GitHub API + age로 fetch → staging에 배치
# appId + installationId 있으면 GitHub Apps JWT 인증, 없으면 gh api 폴백
# $1=hostname, $2=group_name, $3=staging_dir
_fetch_group_secrets() {
    local hostname="$1" group="$2" staging="$3"
    local config
    config=$(_get_secrets_config "$hostname")

    local repo
    repo=$(printf '%s' "$config" | jq -r --arg g "$group" '.groups[$g].repo')

    _resolve_age_key_for_repo "$repo"

    # GitHub Apps 토큰 발급 (appId + installationId 둘 다 있을 때만)
    local _apps_token=""
    local _app_id _inst_id
    _app_id=$(printf '%s' "$config" | jq -r '.appId // empty')
    _inst_id=$(printf '%s' "$config" | jq -r --arg g "$group" '.groups[$g].installationId // empty')
    if [ -n "$_app_id" ] && [ -n "$_inst_id" ]; then
        _resolve_github_apps_pem
        _apps_token=$(_github_apps_token "$_app_id" "$_inst_id" "$REPLY_GITHUB_APPS_PEM")
    fi

    local remote server
    while IFS=$'\t' read -r remote server; do
        local dest="$staging/$server"
        mkdir -p "$(dirname "$dest")"

        log_msg "Task" "[$group] fetch: $remote"
        local _fetch_err
        _fetch_err=$(mktemp)
        local _blob_sha _fetch_ok=0
        if [ -n "$_apps_token" ]; then
            _blob_sha=$(_gh_curl "$_apps_token" GET "repos/$repo/contents/${remote}.age" \
                | jq -r '.sha' 2>"$_fetch_err")
            { _gh_curl "$_apps_token" GET "repos/$repo/git/blobs/$_blob_sha" \
                | jq -r '.content' | tr -d '\n' | base64 -d \
                | age -d -i "$REPLY_AGE_KEY" > "$dest"; } 2>>"$_fetch_err" && _fetch_ok=1
        else
            _blob_sha=$(gh api "repos/$repo/contents/${remote}.age" --jq '.sha' 2>"$_fetch_err")
            { gh api "repos/$repo/git/blobs/$_blob_sha" --jq '.content' \
                | tr -d '\n' | base64 -d \
                | age -d -i "$REPLY_AGE_KEY" > "$dest"; } 2>>"$_fetch_err" && _fetch_ok=1
        fi
        if [ "$_fetch_ok" -eq 0 ]; then
            log_msg "Warn" "[$group] fetch 실패: $remote"
            [ -s "$_fetch_err" ] && sed 's/^/  /' "$_fetch_err" >&2
            rm -f "$_fetch_err"
            printf '  로컬 파일로 대신 입력하시겠습니까? (y/N): '
            local _fallback
            read -r _fallback < /dev/tty
            if [[ "${_fallback:-N}" =~ ^[Yy]$ ]]; then
                while true; do
                    printf '  파일 경로 (Tab 완성): '
                    read -re _fallback < /dev/tty
                    _fallback="${_fallback/#\~/$HOME}"
                    [ -f "$_fallback" ] && break
                    printf '  오류: 파일 없음: %s\n' "$_fallback"
                done
                cp "$_fallback" "$dest"
            else
                log_msg "Error" "[$group] 시크릿 fetch 실패, 배포 중단"
                exit 1
            fi
        else
            rm -f "$_fetch_err"
        fi
        chmod 600 "$dest"
    done < <(printf '%s' "$config" | jq -r --arg g "$group" \
        '.groups[$g].secrets | to_entries[] | [.key, .value] | @tsv')
}

# _check로 주입 항목 선택 → REPLY_CHECKED[]
# groups 키 + from-new.sh 감지
_select_entries() {
    local hostname="$1"
    local config
    config=$(_get_secrets_config "$hostname") || { REPLY_CHECKED=(); return; }

    local -a check_args=()

    while IFS= read -r group; do
        local repo secret_count
        repo=$(printf '%s' "$config" | jq -r --arg g "$group" '.groups[$g].repo')
        secret_count=$(printf '%s' "$config" | jq -r --arg g "$group" '.groups[$g].secrets | length')
        check_args+=("group:$group" "${group}  (${secret_count}개 시크릿, ${repo})")
    done < <(printf '%s' "$config" | jq -r '(.groups // {}) | keys[]')

    local secrets_dir="$NIXOS_PATH/hosts/_deploy/${hostname}.secrets"
    while IFS= read -r new_script; do
        local grp_name
        grp_name=$(basename "$(dirname "$new_script")")
        check_args+=("new:$new_script" "${grp_name} 새 발급  [from-new.sh]")
    done < <(find "$secrets_dir" -name "from-new.sh" -type f 2>/dev/null | sort)

    [ "${#check_args[@]}" -eq 0 ] && { REPLY_CHECKED=(); return; }

    _check "주입할 시크릿 선택  ($hostname)  기본=건너뜀" "${check_args[@]}"
}

# staging 디렉터리를 원격 호스트에 tar pipe로 전송
# $1=hostname, $2=ssh_user, $3=ip, $4=ssh_key(비밀번호 인증 시 비움), $5...=ssh_opts
# 비밀번호 인증: _SECRETS_SSH_PASS 변수를 설정하고 ssh_key를 비워서 호출
_transfer_secrets() {
    local hostname="$1" ssh_user="$2" ip="$3" ssh_key="$4"
    shift 4
    local ssh_opts=("$@")
    local staging="$REPLY_STAGING_DIR"
    local sudo_pfx=""
    [ "$ssh_user" != "root" ] && sudo_pfx="sudo "

    log_msg "Task" "시크릿 전송 중 → $hostname ($ip)"
    if [ -n "${_SECRETS_SSH_PASS:-}" ]; then
        tar -C "$staging" -cf - . | \
            sshpass -f <(printf '%s' "$_SECRETS_SSH_PASS") \
            ssh -o PasswordAuthentication=yes -o PubkeyAuthentication=no \
            "${ssh_opts[@]}" "${ssh_user}@${ip}" \
            "${sudo_pfx}tar -C / -xf - --no-same-owner --no-overwrite-dir"
        sshpass -f <(printf '%s' "$_SECRETS_SSH_PASS") \
            ssh -o PasswordAuthentication=yes -o PubkeyAuthentication=no \
            "${ssh_opts[@]}" "${ssh_user}@${ip}" \
            "${sudo_pfx}systemd-tmpfiles --create" 2>/dev/null || true
    else
        tar -C "$staging" -cf - . | \
            ssh -i "$ssh_key" "${ssh_opts[@]}" "${ssh_user}@${ip}" \
                "${sudo_pfx}tar -C / -xf - --no-same-owner --no-overwrite-dir"
        # 전송 후 tmpfiles 규칙 적용 (소유자·권한 교정)
        ssh -i "$ssh_key" "${ssh_opts[@]}" "${ssh_user}@${ip}" \
            "${sudo_pfx}systemd-tmpfiles --create" 2>/dev/null || true
    fi
    log_msg "Done" "시크릿 전송 완료"
}

# from-new.sh 실행 후 생성된 파일을 nix-secrets 레포에 업로드 (선택적)
# $1=hostname, $2=grp_name, $3=staging
_upload_generated_secrets() {
    local hostname="$1" grp_name="$2" staging="$3"

    local config
    config=$(_get_secrets_config "$hostname") || return 0

    local repo
    repo=$(printf '%s' "$config" | jq -r --arg g "$grp_name" '.groups[$g].repo // empty')
    [ -z "$repo" ] || [ "$repo" = "null" ] && return 0

    # GitHub Apps 토큰 발급
    local _apps_token=""
    local _app_id _inst_id
    _app_id=$(printf '%s' "$config" | jq -r '.appId // empty')
    _inst_id=$(printf '%s' "$config" | jq -r --arg g "$grp_name" '.groups[$g].installationId // empty')
    if [ -n "$_app_id" ] && [ -n "$_inst_id" ]; then
        _resolve_github_apps_pem
        _apps_token=$(_github_apps_token "$_app_id" "$_inst_id" "$REPLY_GITHUB_APPS_PEM")
    fi

    printf '\n'
    printf '  발급된 시크릿을 nix-secrets 레포에도 업로드하시겠습니까? (y/N): '
    local _ans
    read -r _ans < /dev/tty
    [[ "${_ans:-N}" =~ ^[Yy]$ ]] || return 0

    log_msg "Task" "레포 공개키 조회 중..."
    local _pubkey
    if [ -n "$_apps_token" ]; then
        _pubkey=$(_gh_curl "$_apps_token" GET "repos/$repo/contents/.pubkey" \
            | jq -r '.content' 2>/dev/null | base64 -d | tr -d '\n') || {
            log_msg "Warn" ".pubkey 조회 실패, 업로드를 건너뜁니다"
            return 0
        }
    else
        _pubkey=$(gh api "repos/$repo/contents/.pubkey" --jq '.content' 2>/dev/null | base64 -d | tr -d '\n') || {
            log_msg "Warn" ".pubkey 조회 실패, 업로드를 건너뜁니다"
            return 0
        }
    fi

    while IFS=$'\t' read -r remote server; do
        local _src="$staging/$server"
        [ -f "$_src" ] || continue

        log_msg "Task" "암호화 + 업로드: $remote"
        local _encrypted
        _encrypted=$(age -r "$_pubkey" < "$_src" | base64 | tr -d '\n')

        local _api_path="repos/$repo/contents/${remote}.age"
        local _sha=""
        if [ -n "$_apps_token" ]; then
            _sha=$(_gh_curl "$_apps_token" GET "$_api_path" | jq -r '.sha' 2>/dev/null || true)
            if [ -n "$_sha" ]; then
                _gh_curl "$_apps_token" PUT "$_api_path" \
                    "$(jq -n --arg m "update: $remote (from-new)" \
                              --arg c "$_encrypted" --arg s "$_sha" \
                              '{message:$m,content:$c,sha:$s}')" &>/dev/null
            else
                _gh_curl "$_apps_token" PUT "$_api_path" \
                    "$(jq -n --arg m "add: $remote (from-new)" \
                              --arg c "$_encrypted" \
                              '{message:$m,content:$c}')" &>/dev/null
            fi
        else
            _sha=$(gh api "$_api_path" --jq '.sha' 2>/dev/null || true)
            if [ -n "$_sha" ]; then
                gh api "$_api_path" -X PUT \
                    -f message="update: $remote (from-new)" \
                    -f content="$_encrypted" \
                    -f sha="$_sha" &>/dev/null
            else
                gh api "$_api_path" -X PUT \
                    -f message="add: $remote (from-new)" \
                    -f content="$_encrypted" &>/dev/null
            fi
        fi
        log_msg "Done" "업로드 완료: ${remote}.age"
    done < <(printf '%s' "$config" | jq -r --arg g "$grp_name" \
        '.groups[$g].secrets | to_entries[] | [.key, .value] | @tsv')
}

# 메인 함수: 항목 선택 → fetch → 원격 전송
# $1=hostname, $2=ssh_user, $3=ip, $4=ssh_key, $5...=ssh_opts
inject_secrets() {
    local hostname="$1" ssh_user="$2" ip="$3" ssh_key="$4"
    shift 4
    local ssh_opts=("$@")

    _select_entries "$hostname"
    [ "${#REPLY_CHECKED[@]}" -eq 0 ] && return 0

    local staging
    staging=$(mktemp -d)
    REPLY_STAGING_DIR="$staging"
    # shellcheck disable=SC2064
    trap "rm -rf '$staging'" RETURN

    local any_fetched=0
    for entry in "${REPLY_CHECKED[@]}"; do
        local typ="${entry%%:*}"
        local val="${entry#*:}"

        if [ "$typ" = "group" ]; then
            _fetch_group_secrets "$hostname" "$val" "$staging"
            any_fetched=1
        elif [ "$typ" = "new" ]; then
            local grp_name
            grp_name=$(basename "$(dirname "$val")")
            log_msg "Task" "시크릿 새 발급 중: $grp_name/from-new.sh"
            bash "$val" "$staging"
            log_msg "Done" "$grp_name 발급 완료"
            _upload_generated_secrets "$hostname" "$grp_name" "$staging"
            any_fetched=1
        fi
    done

    [ "$any_fetched" -eq 0 ] && return 0

    _transfer_secrets "$hostname" "$ssh_user" "$ip" "$ssh_key" "${ssh_opts[@]}"
}

# rnixup용: resolved.json 기반으로 deploy 호스트 전체에 inject
inject_all_remote_secrets() {
    local resolved_json="$JSON_DIR/resolved.json"
    local hostname

    while IFS= read -r hostname; do
        [ -n "${DEPLOY_NODE:-}" ] && [ "$hostname" != "$DEPLOY_NODE" ] && continue
        _get_secrets_config "$hostname" &>/dev/null || continue

        local ip ssh_key username
        ip=$(jq -r --arg h "$hostname" '.[$h].deploy.ip' "$resolved_json")
        ssh_key=$(jq -r --arg h "$hostname" '.[$h].deploy.sshKey' "$resolved_json")
        username=$(jq -r --arg h "$hostname" '.[$h].username' "$resolved_json")
        ssh_key="${ssh_key/#\~/$HOME}"

        local ssh_opts=(
            -o StrictHostKeyChecking=yes
            -o BatchMode=yes
            -o UserKnownHostsFile="$HOME/.ssh/known_hosts"
            -o LogLevel=ERROR
        )
        inject_secrets "$hostname" "$username" "$ip" "$ssh_key" "${ssh_opts[@]}"
    done < <(jq -r 'to_entries[] | select(.value.deploy != null) | .key' "$resolved_json")
}
