#!/usr/bin/env bash
# nixsec.task-init.sh — nix-secrets GitHub 프라이빗 레포 초기화

_run_init() {
    log_msg "Task" "새 레포 초기화"
    printf '\n'

    command -v age-keygen &>/dev/null || {
        log_msg "Error" "age-keygen이 필요합니다.  nix-shell -p age"; exit 1
    }

    # 기본 레포명: <gh-login>/nix-secrets
    local _login
    _login=$(gh api user --jq '.login' 2>/dev/null || true)
    local _default_repo="${_login:+${_login}/}nix-secrets"

    log_msg "Input" "레포 이름 (Enter = 기본값, org/repo 형태도 가능)"
    local _input
    # read -p로 프롬프트를 readline에 전달해야 백스페이스가 프롬프트 앞으로 넘어가지 않음
    read -rep "  [$_default_repo]: " _input
    local _repo="${_input:-$_default_repo}"
    # owner 없이 입력한 경우 (예: "my-secrets") → 자동으로 "<login>/my-secrets"으로 보완
    [[ "$_repo" != */* ]] && _repo="${_login}/${_repo}"

    # age 키 생성 — ~/.local/share/nix-secrets/ 에 영구 저장 (재부팅 후에도 유지)
    local _slug="${_repo//\//-}"
    local _key_dir="$HOME/.local/share/nix-secrets"
    local _key_file="$_key_dir/${_slug}.age.key"
    mkdir -p "$_key_dir"
    chmod 700 "$_key_dir"
    printf '\n'
    log_msg "Task" "age 전용 키 생성 중..."
    age-keygen -o "$_key_file" || { log_msg "Error" "age 키 생성 실패"; exit 1; }
    chmod 600 "$_key_file"
    local _pubkey
    _pubkey=$(age-keygen -y "$_key_file") || { log_msg "Error" "공개키 추출 실패"; exit 1; }

    # 키 경로 캐싱
    local _cache="$HOME/.cache/nix-secrets/${_slug}.key-path"
    mkdir -p "$(dirname "$_cache")"
    printf '%s' "$_key_file" > "$_cache"

    log_msg "Notice" "공개키: $_pubkey"
    log_msg "Notice" "개인키: $_key_file"

    # GitHub 레포 생성
    printf '\n'
    log_msg "Task" "GitHub 프라이빗 레포 생성 중: $_repo"
    gh repo create "$_repo" --private 2>/dev/null || {
        log_msg "Error" "레포 생성 실패 (이미 존재하거나 권한 없음)"; exit 1
    }

    # .pubkey 업로드
    log_msg "Task" ".pubkey 업로드 중..."
    local _encoded
    _encoded=$(printf '%s\n' "$_pubkey" | base64 | tr -d '\n')
    gh api "repos/$_repo/contents/.pubkey" \
        -X PUT \
        -f message="init: add age public key" \
        -f content="$_encoded" \
        &>/dev/null
    log_msg "Done" "레포 생성 완료: https://github.com/$_repo"

    printf '\n'
    printf '════════════════════════════════════════════════════════\n'
    printf '  ⚠  개인키를 Google Drive에 지금 바로 백업하세요\n'
    printf '\n'
    printf '     파일: %s\n' "$_key_file"
    printf '\n'
    printf '  백업 후 로컬 복사본은 삭제해도 됩니다.\n'
    printf '  (캐시: %s)\n' "$_cache"
    printf '\n'
    printf '  secrets.json의 "repo" 값을 업데이트하세요:\n'
    printf '    "repo": "%s"\n' "$_repo"
    printf '════════════════════════════════════════════════════════\n\n'
}
