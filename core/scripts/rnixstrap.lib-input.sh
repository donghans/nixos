#!/usr/bin/env bash
# rnixstrap.lib-input.sh — Phase 1 대화형 입력 수집 + UI 헬퍼
# 변수 의존: NIXOS_PATH, _HOST_IS_NEW, _TOML_IP, _TOML_SSH_KEY
# _pick / _check 는 nixup.lib-ui.sh에서 제공됨 (rnixstrap.sh가 먼저 source)


# ── _copy_key_to_rnixup ───────────────────────────────────────────────────────
# 선택된 SSH 키를 ~/.ssh/rnixup/<hostname>.<ext> 로 복사하고 _SSH_KEY 경로를 갱신.
# 이미 정규 경로에 있으면 no-op.
_copy_key_to_rnixup() {
    local rnixup_dir="$HOME/.ssh/rnixup"
    local base ext
    base=$(basename "$_SSH_KEY")
    ext="${base##*.}"
    [ "$ext" = "$base" ] && ext="pem"   # 확장자 없으면 pem 사용
    local dest="$rnixup_dir/${_HOSTNAME}.${ext}"
    if [ "$_SSH_KEY" = "$dest" ]; then
        return  # 이미 정규 경로
    fi
    mkdir -p "$rnixup_dir"
    chmod 700 "$rnixup_dir"
    cp "$_SSH_KEY" "$dest"
    chmod 600 "$dest"
    _SSH_KEY="$dest"
    log_msg "Done" "키 복사: ~/.ssh/rnixup/${_HOSTNAME}.${ext}"
}

# ── _load_toml_values ─────────────────────────────────────────────────────────
# [deploy] 있는 기존 호스트: ip/sshKey/bootLoader/diskDevice/system 로드
# → _TOML_IP, _TOML_SSH_KEY, _TOML_BOOT_LOADER, _TOML_DISK_DEVICE, _SYSTEM 설정
_load_toml_values() {
    local toml_path="$NIXOS_PATH/hosts/${_HOSTNAME}.toml"
    local result
    result=$(python3 - "$toml_path" <<'EOF'
import sys, tomllib
with open(sys.argv[1], "rb") as f:
    d = tomllib.load(f)
deploy = d.get("deploy", {})
print(deploy.get("ip", ""))
print(deploy.get("sshKey", ""))
print(deploy.get("sshUser", ""))
print(d.get("bootLoader", ""))
print(d.get("diskDevice", ""))
print(d.get("system", "x86_64-linux"))
print(d.get("cloud", ""))
EOF
)
    mapfile -t _toml_fields <<< "$result"
    _TOML_IP="${_toml_fields[0]:-}"
    _TOML_SSH_KEY="${_toml_fields[1]:-}"
    _TOML_SSH_USER="${_toml_fields[2]:-}"
    _TOML_BOOT_LOADER="${_toml_fields[3]:-}"
    _TOML_DISK_DEVICE="${_toml_fields[4]:-}"
    _BOOT_LOADER="$_TOML_BOOT_LOADER"
    _DISK_DEVICE="$_TOML_DISK_DEVICE"
    _SYSTEM="${_toml_fields[5]:-x86_64-linux}"
    _TOML_CLOUD="${_toml_fields[6]:-}"
    log_msg "Init" "TOML 로드: ip=${_TOML_IP}, system=${_SYSTEM}, boot=${_BOOT_LOADER}"
}

# ── _load_toml_type ────────────────────────────────────────────────────────────
# [deploy] 없는 standalone 호스트: type/system/diskDevice/bootLoader 로드
# → _TOML_BOOT_LOADER, _TOML_DISK_DEVICE, _SYSTEM 설정 (ip/sshKey 없음)
_load_toml_type() {
    local toml_path="$NIXOS_PATH/hosts/${_HOSTNAME}.toml"
    local result
    result=$(python3 - "$toml_path" <<'EOF'
import sys, tomllib
with open(sys.argv[1], "rb") as f:
    d = tomllib.load(f)
print(d.get("bootLoader", ""))
print(d.get("diskDevice", ""))
print(d.get("system", "x86_64-linux"))
EOF
)
    mapfile -t _toml_fields <<< "$result"
    _TOML_BOOT_LOADER="${_toml_fields[0]:-}"
    _TOML_DISK_DEVICE="${_toml_fields[1]:-}"
    _BOOT_LOADER="$_TOML_BOOT_LOADER"
    _DISK_DEVICE="$_TOML_DISK_DEVICE"
    _SYSTEM="${_toml_fields[2]:-x86_64-linux}"
    log_msg "Init" "TOML 로드 (standalone): system=${_SYSTEM}, boot=${_BOOT_LOADER}"
}

# ── load_bootstrap_env ─────────────────────────────────────────────────────────
# standalone 호스트: ~/.ssh/rnixup/<hostname>.bootstrap.env 에서 기본값 로드
# → _BOOTSTRAP_IP, _BOOTSTRAP_SSH_KEY, _BOOTSTRAP_SSH_USER 설정
load_bootstrap_env() {
    local env_file="$HOME/.ssh/rnixup/${_HOSTNAME}.bootstrap.env"
    [ -f "$env_file" ] || return 0
    local line key value
    while IFS= read -r line; do
        [[ "$line" =~ ^([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
        key="${BASH_REMATCH[1]}"
        value="${BASH_REMATCH[2]}"
        case "$key" in
            _IP)       _BOOTSTRAP_IP="$value" ;;
            _SSH_KEY)  _BOOTSTRAP_SSH_KEY="${value/#\~/$HOME}" ;;
            _SSH_USER) _BOOTSTRAP_SSH_USER="$value" ;;
        esac
    done < "$env_file"
    log_msg "Init" "bootstrap.env 로드: $env_file"
}

# ── _enter_new_hostname ────────────────────────────────────────────────────────
_enter_new_hostname() {
    while true; do
        printf "\n"
        read -rp "$(_log_prompt)새 호스트 이름 (영문·숫자·하이픈, 예: my-server): " _HOSTNAME
        _HOSTNAME="${_HOSTNAME// /}"
        if [ -z "$_HOSTNAME" ]; then
            log_msg "Error" "hostname은 필수입니다."; continue
        fi
        if [[ ! "$_HOSTNAME" =~ ^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$ ]]; then
            log_msg "Error" "유효하지 않은 hostname: '$_HOSTNAME'"; continue
        fi
        if [ -f "$NIXOS_PATH/hosts/${_HOSTNAME}.toml" ]; then
            log_msg "Error" "이미 존재하는 호스트: hosts/${_HOSTNAME}.toml"
            log_msg "Notice" "목록에서 선택하거나 rnixup으로 배포하세요."; continue
        fi
        break
    done
}

# ── select_or_create_hostname ─────────────────────────────────────────────────
# 모든 hosts/*.toml(언더스코어 제외) 표시 후 선택.
#   [deploy] 있음 → "[1.2.3.4]" 레이블 → 재설치 모드
#   [deploy] 없음 → "[type]"    레이블 → standalone bootstrap 모드
# 기존 호스트 없으면 텍스트 입력.
# → _HOSTNAME, _HOST_IS_NEW, _HOST_HAS_DEPLOY 설정.
select_or_create_hostname() {
    local -a _all_hosts=() _all_labels=() _has_deploy=()
    local _f _n _label_val _has
    for _f in "$NIXOS_PATH/hosts/"*.toml; do
        [ -f "$_f" ] || continue
        _n=$(basename "$_f" .toml)
        [[ "$_n" == _* ]] && continue
        if grep -q '^\[deploy\]' "$_f" 2>/dev/null; then
            _label_val=$(python3 - "$_f" 2>/dev/null <<'EOF' || echo "?"
import sys, tomllib
with open(sys.argv[1], "rb") as f:
    d = tomllib.load(f)
print(d.get("deploy", {}).get("ip", "?"))
EOF
)
            _has="true"
        else
            _label_val=$(python3 - "$_f" 2>/dev/null <<'EOF' || echo "server"
import sys, tomllib
with open(sys.argv[1], "rb") as f:
    d = tomllib.load(f)
print(d.get("type", "server"))
EOF
)
            _has="false"
        fi
        _all_hosts+=("$_n")
        _all_labels+=("$(printf "%-28s [%s]" "$_n" "$_label_val")")
        _has_deploy+=("$_has")
    done

    if [ "${#_all_hosts[@]}" -eq 0 ]; then
        _HOST_IS_NEW=true
        _HOST_HAS_DEPLOY=true
        _enter_new_hostname
        return
    fi

    local -a _pick_items=("${_all_labels[@]}" "+ 새 호스트 추가")
    _pick "호스트 선택  재설치=[IP] / standalone=[type] / 신규=아래로:" "${_pick_items[@]}"

    if [ "$REPLY" -lt "${#_all_hosts[@]}" ]; then
        _HOSTNAME="${_all_hosts[$REPLY]}"
        _HOST_IS_NEW=false
        _HOST_HAS_DEPLOY="${_has_deploy[$REPLY]}"
        if [ "$_HOST_HAS_DEPLOY" = true ]; then
            _load_toml_values
            log_msg "Done" "선택: $_HOSTNAME (재설치 모드)"
        else
            _load_toml_type
            log_msg "Done" "선택: $_HOSTNAME (standalone bootstrap 모드)"
        fi
    else
        _HOST_IS_NEW=true
        _HOST_HAS_DEPLOY=true
        _enter_new_hostname
    fi
}

# ── ask_ssh_user ──────────────────────────────────────────────────────────────
ask_ssh_user() {
    local _default="${_BOOTSTRAP_SSH_USER:-root}"
    printf "\n"
    read -rp "$(_log_prompt)bootstrap SSH 유저 [${_default}]  (AWS Lightsail/EC2는 ec2-user): " _input
    _SSH_USER="${_input:-${_default}}"
    _SSH_USER="${_SSH_USER// /}"
    log_msg "Done" "bootstrap SSH 유저: $_SSH_USER"
}

# ── ask_ip ────────────────────────────────────────────────────────────────────
ask_ip() {
    while true; do
        printf "\n"
        local _ip_default="${_TOML_IP:-${_BOOTSTRAP_IP:-}}"
        local _ip_prompt
        if [ -n "$_ip_default" ]; then
            _ip_prompt="$(_log_prompt)공인 IP 주소 [현재: $_ip_default]: "
        else
            _ip_prompt="$(_log_prompt)공인 IP 주소: "
        fi
        read -rp "$_ip_prompt" _input
        _IP="${_input:-${_ip_default}}"
        _IP="${_IP// /}"
        if [ -z "$_IP" ]; then
            log_msg "Error" "IP 주소는 필수입니다."; continue
        fi
        # 기본 IPv4 형식 검사 (완전 검증 아님)
        if [[ ! "$_IP" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
            log_msg "Error" "올바른 IPv4 형식이 아닙니다: $_IP"; continue
        fi
        break
    done
}

# ── ask_ssh_key ───────────────────────────────────────────────────────────────
ask_ssh_key() {
    while true; do
        printf "\n"
        local _key_default="${_TOML_SSH_KEY:-${_BOOTSTRAP_SSH_KEY:-}}"
        # ~/.ssh/rnixup/<hostname>.* 에 이미 복사된 키가 있으면 기본값으로 사용
        if [ -z "$_key_default" ]; then
            local _f
            for _f in "$HOME/.ssh/rnixup/${_HOSTNAME}."*; do
                [[ "$_f" == *.env ]] && continue
                [ -f "$_f" ] && _key_default="$_f" && break
            done
        fi
        local _key_prompt
        if [ -n "$_key_default" ]; then
            _key_prompt="$(_log_prompt_rl)SSH .pem 키 파일 경로 [현재: $_key_default] (Tab 자동완성): "
        else
            _key_prompt="$(_log_prompt_rl)SSH .pem 키 파일 경로 (Tab 자동완성): "
        fi
        read -rep "$_key_prompt" _input
        _SSH_KEY="${_input:-${_key_default}}"
        _SSH_KEY="${_SSH_KEY// /}"
        _SSH_KEY="${_SSH_KEY/#\~/$HOME}"
        if [ -z "$_SSH_KEY" ]; then
            log_msg "Error" "키 파일 경로는 필수입니다."; continue
        fi
        if [ ! -f "$_SSH_KEY" ]; then
            log_msg "Error" "파일 없음: $_SSH_KEY"
            log_msg "Notice" "AWS 콘솔에서 .pem을 다운로드하고 chmod 600으로 권한을 설정하세요."
            continue
        fi
        local perms
        perms=$(stat -c "%a" "$_SSH_KEY" 2>/dev/null || stat -f "%OLp" "$_SSH_KEY" 2>/dev/null || echo "unknown")
        if [ "$perms" != "600" ] && [ "$perms" != "400" ]; then
            log_msg "Warn" "키 파일 권한: $perms (권장: 600)"
            log_msg "Notice" "  chmod 600 \"$_SSH_KEY\""
        fi
        _copy_key_to_rnixup
        break
    done
}

# ── ask_deploy_key ────────────────────────────────────────────────────────────
# 비밀번호 bootstrap 시 NixOS authorized key 등록 + post-bootstrap SSH 접속용 키 입력
# _SSH_KEY 설정 (공개키 등록용), _SSH_PASS는 이미 설정된 상태
ask_deploy_key() {
    printf "\n"
    log_msg "Notice" "NixOS 설치 후 SSH 접속 및 authorized key 등록을 위한 키가 필요합니다."
    while true; do
        local _key_prompt="$(_log_prompt_rl)배포용 SSH 키 파일 경로 (Tab 자동완성, Enter=건너뜀): "
        local _input=""
        read -rep "$_key_prompt" _input
        _input="${_input// /}"
        _input="${_input/#\~/$HOME}"
        if [ -z "$_input" ]; then
            log_msg "Warn" "배포 키 없음 — NixOS 설치 후 SSH 키 인증이 설정되지 않습니다."
            break
        fi
        if [ ! -f "$_input" ]; then
            log_msg "Error" "파일 없음: $_input"; continue
        fi
        _SSH_KEY="$_input"
        local perms
        perms=$(stat -c "%a" "$_SSH_KEY" 2>/dev/null || stat -f "%OLp" "$_SSH_KEY" 2>/dev/null || echo "unknown")
        if [ "$perms" != "600" ] && [ "$perms" != "400" ]; then
            log_msg "Warn" "키 파일 권한: $perms (권장: 600)"
        fi
        _copy_key_to_rnixup
        log_msg "Done" "배포 키: $_SSH_KEY"
        break
    done
}

# ── ask_ssh_auth ──────────────────────────────────────────────────────────────
# SSH 인증 방식 선택: 키 파일 또는 비밀번호
# _SSH_KEY 또는 _SSH_PASS 설정
ask_ssh_auth() {
    printf "\n"
    _pick "SSH 인증 방식:" \
        "키 파일 (.pem)   — 표준 SSH 키 인증" \
        "비밀번호          — 초기 VPS 접속 등"
    if [ "$REPLY" -eq 0 ]; then
        ask_ssh_key
    else
        printf "\n"
        local _pass=""
        while [ -z "$_pass" ]; do
            read -srp "$(_log_prompt)SSH 비밀번호: " _pass
            printf '\n'
            [ -z "$_pass" ] && log_msg "Error" "비밀번호를 입력하세요."
        done
        _SSH_PASS="$_pass"
        log_msg "Done" "비밀번호 인증 선택됨"
        ask_deploy_key
    fi
}

# ── ask_system ────────────────────────────────────────────────────────────────
ask_system() {
    printf "\n"
    _pick "아키텍처 선택:" \
        "x86_64-linux   (일반 64비트, AWS/GCP/Hetzner 기본)" \
        "aarch64-linux  (ARM64, AWS Graviton 등)"
    _SYSTEM="x86_64-linux"
    [ "$REPLY" -eq 1 ] && _SYSTEM="aarch64-linux"
    log_msg "Done" "아키텍처: $_SYSTEM"
}

# ── ask_services ──────────────────────────────────────────────────────────────
ask_services() {
    printf "\n"
    _check "활성화할 서비스 선택:" "${_ALL_SERVICES[@]}"
    _SERVICES=("${REPLY_CHECKED[@]+"${REPLY_CHECKED[@]}"}")
    if [ ${#_SERVICES[@]} -gt 0 ]; then
        log_msg "Done" "선택된 서비스: ${_SERVICES[*]}"
    else
        log_msg "Done" "선택된 서비스 없음 (기본 server 프리셋만 적용)"
    fi
}

