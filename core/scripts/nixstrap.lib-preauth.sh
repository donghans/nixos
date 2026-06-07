#!/usr/bin/env bash
# nixstrap.lib-preauth.sh — headscale preauth key 생성 및 배포 라이브러리
#
# 공개 인터페이스:
#   check_preauth_keys_local  <hostname> [root_prefix]
#       로컬 배포 — resolved.json에서 preauth-keys 읽어 <root_prefix>/var/lib/... 에 배포
#       root_prefix 기본값: /mnt (nixstrap), 빈 문자열 전달 시 / (nixup os)
#   check_preauth_keys_remote <hostname> <ip> <ssh_user> <ssh_key> [ssh_opts...]
#       rnixstrap 전용 — 원격 호스트에 SSH로 배포
#   check_all_preauth_keys_remote
#       rnixup 전용 — resolved.json의 모든 deploy 호스트에 대해 실행
#   _any_remote_preauth_keys_needed
#       rnixup 전용 — preauth-keys가 선언된 deploy 호스트 존재 시 true
#
# 의존:
#   log_msg, _log_prompt   (lib-ui.sh 또는 동등한 함수가 이미 sourced 되어 있어야 함)
#   jq, python3, ssh       PATH에 있어야 함

# ── 전역 상태 (세션 내 캐시) ──────────────────────────────────────────────────
_HS_CONN_ASKED=false    # true: 이미 연결 정보를 입력받음
_HS_DOMAIN=""           # headscale 서버 도메인/IP
_HS_SSH_USER=""         # headscale 서버 SSH 유저
_HS_SSH_KEY=""          # headscale 서버 SSH 키 경로 (/tmp 복사본)
_HS_SSH_KEY_DEFAULT=""  # TOML에서 읽은 기본 키 경로
_HS_SSH_KEY_TMP=""      # /tmp 복사본 경로 (호출 스크립트 trap에서 삭제)
export PREAUTH_KEYS_DEPLOYED=false  # 이번 세션에서 새 key를 배포했으면 true

# 호출 스크립트의 기존 _trap_cleanup / EXIT trap에서 호출
preauth_cleanup_tmp_key() {
    [ -n "${_HS_SSH_KEY_TMP:-}" ] && rm -f "$_HS_SSH_KEY_TMP" 2>/dev/null || true
    _HS_SSH_KEY_TMP=""
}

# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

# nixos repo 루트 경로 반환
_preauth_repo_root() {
    if [ -n "${NIXOS_PATH:-}" ] && [ -d "${NIXOS_PATH:-}" ]; then
        echo "$NIXOS_PATH"
    elif [ -n "${REPO_TMP:-}" ] && [ -d "${REPO_TMP:-}" ]; then
        echo "$REPO_TMP"
    else
        local _dir
        _dir="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"
        readlink -f "$_dir/../.."
    fi
}

# resolved.json 경로 반환
_preauth_resolved_json() {
    if [ -n "${JSON_DIR:-}" ] && [ -f "${JSON_DIR}/resolved.json" ]; then
        echo "${JSON_DIR}/resolved.json"
    elif [ -n "${RESOLVE_TMP:-}" ] && [ -f "${RESOLVE_TMP}/resolved.json" ]; then
        echo "${RESOLVE_TMP}/resolved.json"
    else
        return 1
    fi
}

# [headscale] 기본값 읽기
# 우선순위: ec2-nixos-headscale.toml → lightsail-nixos-headscale.toml (fallback)
_read_headscale_defaults() {
    local _toml
    local _root
    _root="$(_preauth_repo_root)/hosts"
    if [ -f "${_root}/ec2-nixos-headscale.toml" ]; then
        _toml="${_root}/ec2-nixos-headscale.toml"
    elif [ -f "${_root}/lightsail-nixos-headscale.toml" ]; then
        _toml="${_root}/lightsail-nixos-headscale.toml"
    else
        return
    fi

    local _out
    _out=$(python3 - "$_toml" <<'PYEOF'
import tomllib, sys, os
with open(sys.argv[1], "rb") as f:
    d = tomllib.load(f)
hs = d.get("headscale", {})
print(hs.get("domain", ""))
print(hs.get("ssh-user", "ec2-user"))
print(os.path.expanduser(hs.get("ssh-key", "")))
PYEOF
) || return
    _HS_DOMAIN=$(echo "$_out" | sed -n '1p')
    _HS_SSH_USER=$(echo "$_out" | sed -n '2p')
    _HS_SSH_KEY_DEFAULT=$(echo "$_out" | sed -n '3p')
}

# 대화형으로 headscale 연결 정보 입력받기 (세션 내 한 번만)
_ask_headscale_connection() {
    [ "${_HS_CONN_ASKED}" = true ] && return 0

    _read_headscale_defaults

    printf "\n"
    log_msg "Input" "Headscale 연결 정보 입력 (preauth key 생성용)"

    # 도메인
    local _default_domain="${_HS_DOMAIN:-}"
    if [ -n "$_default_domain" ]; then
        read -rp "$(_log_prompt)Headscale 서버 주소 [${_default_domain}]: " _HS_DOMAIN
        _HS_DOMAIN="${_HS_DOMAIN:-$_default_domain}"
    else
        read -rp "$(_log_prompt)Headscale 서버 주소: " _HS_DOMAIN
        [ -z "$_HS_DOMAIN" ] && { log_msg "Error" "서버 주소를 입력해야 합니다."; return 1; }
    fi

    # SSH 유저
    local _default_user="${_HS_SSH_USER:-ec2-user}"
    read -rp "$(_log_prompt)SSH 유저 [${_default_user}]: " _HS_SSH_USER
    _HS_SSH_USER="${_HS_SSH_USER:-$_default_user}"

    # SSH 키
    if [ -n "${_HS_SSH_KEY_DEFAULT:-}" ] && [ -f "${_HS_SSH_KEY_DEFAULT}" ]; then
        read -rp "$(_log_prompt)SSH 키 경로 [${_HS_SSH_KEY_DEFAULT}]: " _HS_SSH_KEY
        _HS_SSH_KEY="${_HS_SSH_KEY:-$_HS_SSH_KEY_DEFAULT}"
    else
        read -re -p "$(_log_prompt)SSH 키 경로: " _HS_SSH_KEY
    fi
    _HS_SSH_KEY="${_HS_SSH_KEY/#\~/$HOME}"
    if [ ! -f "$_HS_SSH_KEY" ]; then
        log_msg "Error" "SSH 키 파일을 찾을 수 없음: $_HS_SSH_KEY"
        return 1
    fi

    # FAT16/32/exFAT 등 권한 미지원 파일시스템 대응:
    # SSH는 600/400 이상 열린 키를 거부하므로 /tmp에 복사 후 chmod 400 적용
    local _key_tmp
    _key_tmp=$(mktemp /tmp/hs-key-XXXXXX)
    cp "$_HS_SSH_KEY" "$_key_tmp"
    chmod 400 "$_key_tmp"
    _HS_SSH_KEY_TMP="$_key_tmp"
    _HS_SSH_KEY="$_key_tmp"

    _HS_CONN_ASKED=true
    log_msg "Done" "연결 정보 입력 완료 (세션 내 재사용됨)"
}

# headscale user 조회 → 없으면 생성 → REPLY_USER_ID에 numeric ID 저장
# headscale v0.27+: -u/--user는 uint(숫자 ID)
_lookup_or_create_headscale_user() {
    local _hs_user="$1"

    local _list_out
    _list_out=$(ssh \
        -i "$_HS_SSH_KEY" \
        -o StrictHostKeyChecking=no \
        -o ConnectTimeout=15 \
        "${_HS_SSH_USER}@${_HS_DOMAIN}" \
        "sudo headscale users list -n '${_hs_user}' --output json 2>/dev/null") \
        || { log_msg "Error" "headscale SSH 접속 실패 (user 조회)"; return 1; }

    REPLY_USER_ID=$(echo "$_list_out" | jq -r '(if type == "array" then .[0] else . end).id // empty' 2>/dev/null)

    if [ -z "${REPLY_USER_ID:-}" ]; then
        log_msg "Task" "headscale user '${_hs_user}' 없음 — 생성 중..."
        local _create_out
        _create_out=$(ssh \
            -i "$_HS_SSH_KEY" \
            -o StrictHostKeyChecking=no \
            -o ConnectTimeout=15 \
            "${_HS_SSH_USER}@${_HS_DOMAIN}" \
            "sudo headscale users create '${_hs_user}' --output json") \
            || { log_msg "Error" "headscale user 생성 실패"; return 1; }

        REPLY_USER_ID=$(echo "$_create_out" | jq -r '(if type == "array" then .[0] else . end).id // empty')
        if [ -z "${REPLY_USER_ID:-}" ]; then
            log_msg "Error" "headscale user 생성 후 ID 획득 실패. 응답: $_create_out"
            return 1
        fi
        log_msg "Done" "headscale user '${_hs_user}' 생성 완료 (ID: ${REPLY_USER_ID})"
    fi
}

# headscale SSH로 preauth key 생성 → REPLY_PREAUTH_KEY
_generate_preauth_key() {
    local _hs_user="$1" _key_name="$2"
    log_msg "Task" "headscale preauth key 생성 중: user=${_hs_user}, name=${_key_name}"

    REPLY_USER_ID=""
    _lookup_or_create_headscale_user "$_hs_user" || return 1

    local _json_out
    _json_out=$(ssh \
        -i "$_HS_SSH_KEY" \
        -o StrictHostKeyChecking=no \
        -o ConnectTimeout=15 \
        "${_HS_SSH_USER}@${_HS_DOMAIN}" \
        "sudo headscale preauthkeys create -u ${REPLY_USER_ID} --expiration 24h --output json") \
        || { log_msg "Error" "headscale SSH 접속 실패 (key 생성)"; return 1; }

    REPLY_PREAUTH_KEY=$(echo "$_json_out" | jq -r '.key // empty')
    if [ -z "${REPLY_PREAUTH_KEY:-}" ]; then
        log_msg "Error" "preauth key 생성 실패. headscale 응답: $_json_out"
        return 1
    fi
    log_msg "Done" "preauth key 생성 완료"
}

# ── 공개 함수 ────────────────────────────────────────────────────────────────

# 로컬 배포: <root_prefix>/var/lib/nix-secrets/tailscale/ 에 배포
# $1 = hostname
# $2 = root_prefix (기본값: /mnt — nixstrap용, 빈 문자열 = 실행 중인 시스템에 직접 배포)
check_preauth_keys_local() {
    local _hostname="$1"
    local _root="${2-/mnt}"  # 미전달 시 /mnt, 빈 문자열 전달 시 ""

    local _resolved
    _resolved=$(_preauth_resolved_json) || {
        log_msg "Warn" "resolved.json 미발견 — preauth key 배포 건너뜀"
        return 0
    }

    local _keys_json
    _keys_json=$(jq -r --arg h "$_hostname" '.[$h].preauthKeys // [] | @json' "$_resolved")
    local _count
    _count=$(echo "$_keys_json" | jq 'length')
    [ "$_count" -eq 0 ] && return 0

    local _any_missing=false
    local _i=0
    while [ "$_i" -lt "$_count" ]; do
        local _user _name _dest
        _user=$(echo "$_keys_json" | jq -r ".[$_i].user")
        _name=$(echo "$_keys_json" | jq -r ".[$_i].name")
        _dest="${_root}/var/lib/nix-secrets/tailscale/${_user}/${_name}.preauth-key"
        if [ ! -f "$_dest" ]; then
            _any_missing=true
            break
        fi
        _i=$(( _i + 1 ))
    done

    [ "$_any_missing" = false ] && return 0

    _ask_headscale_connection || return 1

    _i=0
    while [ "$_i" -lt "$_count" ]; do
        local _user _name _dest
        _user=$(echo "$_keys_json" | jq -r ".[$_i].user")
        _name=$(echo "$_keys_json" | jq -r ".[$_i].name")
        _dest="${_root}/var/lib/nix-secrets/tailscale/${_user}/${_name}.preauth-key"
        if [ -f "$_dest" ]; then
            log_msg "Notice" "이미 존재: ${_dest#"${_root}"}"
            _i=$(( _i + 1 ))
            continue
        fi
        REPLY_PREAUTH_KEY=""
        _generate_preauth_key "$_user" "$_name" || return 1
        sudo mkdir -p "$(dirname "$_dest")"
        printf '%s' "$REPLY_PREAUTH_KEY" | sudo tee "$_dest" > /dev/null
        sudo chmod 600 "$_dest"
        log_msg "Done" "배포 완료: ${_dest#"${_root}"}"
        export PREAUTH_KEYS_DEPLOYED=true
        _i=$(( _i + 1 ))
    done
}

# rnixstrap 전용: 원격 호스트에 SSH로 배포
# $1=hostname $2=ip $3=ssh_user $4=ssh_key [ssh_opts...]
check_preauth_keys_remote() {
    local _hostname="$1" _ip="$2" _ssh_user="$3" _ssh_key="$4"
    shift 4
    local _ssh_opts=("$@")
    local _sudo_pfx=""
    [ "$_ssh_user" != "root" ] && _sudo_pfx="sudo "

    local _resolved
    _resolved=$(_preauth_resolved_json) || {
        log_msg "Warn" "resolved.json 미발견 — preauth key 배포 건너뜀"
        return 0
    }

    local _keys_json
    _keys_json=$(jq -r --arg h "$_hostname" '.[$h].preauthKeys // [] | @json' "$_resolved")
    local _count
    _count=$(echo "$_keys_json" | jq 'length')
    [ "$_count" -eq 0 ] && return 0

    local _any_missing=false
    local _i=0
    while [ "$_i" -lt "$_count" ]; do
        local _user _name _dest
        _user=$(echo "$_keys_json" | jq -r ".[$_i].user")
        _name=$(echo "$_keys_json" | jq -r ".[$_i].name")
        _dest="/var/lib/nix-secrets/tailscale/${_user}/${_name}.preauth-key"
        if ! ssh -i "$_ssh_key" "${_ssh_opts[@]}" "${_ssh_user}@${_ip}" \
                "${_sudo_pfx}test -f '${_dest}'" 2>/dev/null; then
            _any_missing=true
            break
        fi
        _i=$(( _i + 1 ))
    done

    [ "$_any_missing" = false ] && return 0

    _ask_headscale_connection || return 1

    _i=0
    while [ "$_i" -lt "$_count" ]; do
        local _user _name _dest
        _user=$(echo "$_keys_json" | jq -r ".[$_i].user")
        _name=$(echo "$_keys_json" | jq -r ".[$_i].name")
        _dest="/var/lib/nix-secrets/tailscale/${_user}/${_name}.preauth-key"
        if ssh -i "$_ssh_key" "${_ssh_opts[@]}" "${_ssh_user}@${_ip}" \
                "${_sudo_pfx}test -f '${_dest}'" 2>/dev/null; then
            log_msg "Notice" "이미 존재 (원격): $_hostname $_dest"
            _i=$(( _i + 1 ))
            continue
        fi
        REPLY_PREAUTH_KEY=""
        _generate_preauth_key "$_user" "$_name" || return 1
        ssh -i "$_ssh_key" "${_ssh_opts[@]}" "${_ssh_user}@${_ip}" \
            "${_sudo_pfx}mkdir -p '$(dirname "${_dest}")'"
        printf '%s' "$REPLY_PREAUTH_KEY" | \
            ssh -i "$_ssh_key" "${_ssh_opts[@]}" "${_ssh_user}@${_ip}" \
            "${_sudo_pfx}tee '${_dest}' > /dev/null && ${_sudo_pfx}chmod 600 '${_dest}'"
        log_msg "Done" "배포 완료 (원격): $_hostname $_dest"
        _i=$(( _i + 1 ))
    done
}

# rnixup 전용: resolved.json의 deploy 호스트 중 preauthKeys 비어있지 않은 곳이 있으면 true
_any_remote_preauth_keys_needed() {
    local _resolved
    _resolved=$(_preauth_resolved_json) || return 1
    local _count
    _count=$(jq '[to_entries[] | select(.value.deploy != null and (.value.preauthKeys | length) > 0)] | length' "$_resolved")
    [ "${_count:-0}" -gt 0 ]
}

# rnixup 전용: resolved.json의 모든 deploy 호스트에 preauth key 배포
check_all_preauth_keys_remote() {
    local _resolved
    _resolved=$(_preauth_resolved_json) || {
        log_msg "Warn" "resolved.json 미발견 — preauth key 배포 건너뜀"
        return 0
    }

    while IFS=$'\t' read -r _hostname _ip _ssh_key _ssh_user; do
        local _keys_json
        _keys_json=$(jq -r --arg h "$_hostname" '.[$h].preauthKeys // [] | @json' "$_resolved")
        local _count
        _count=$(echo "$_keys_json" | jq 'length')
        [ "$_count" -eq 0 ] && continue

        log_msg "Task" "[$_hostname] preauth key 확인 중..."
        local _ssh_opts=(-o StrictHostKeyChecking=no -o ConnectTimeout=15)
        check_preauth_keys_remote \
            "$_hostname" "$_ip" "$_ssh_user" "$_ssh_key" "${_ssh_opts[@]}"
    done < <(jq -r '
        to_entries[]
        | select(.value.deploy != null and (.value.preauthKeys | length) > 0)
        | [.key, .value.deploy.targetHost, .value.deploy.sshKey, .value.username]
        | @tsv
    ' "$_resolved")
}
