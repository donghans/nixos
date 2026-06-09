#!/usr/bin/env nix-shell
#!nix-shell -i bash -I nixpkgs=flake:nixpkgs -p jq python3 git openssh age curl openssl sshpass
# shellcheck disable=SC1008,SC1091,SC2034,SC2154
set -euo pipefail

SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
NIXOS_PATH=$(readlink -f "$SCRIPT_DIR/../..")

source "$SCRIPT_DIR/nixup.lib-ui.sh"
_LOG_PREFIX="RNIXSTRAP"
_LOG_CAT[Review]="$CYAN"

# ── 도움말 ────────────────────────────────────────────────────────────────────
if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
    printf "\n"
    printf "${_LOG_PREFIX_COLOR}${_LOG_PREFIX}${NC} ${CYAN}%-9s${NC} | 원격 NixOS 호스트 초기 설치 도구\n" "Help"
    printf "\n"
    printf "  사용법:\n"
    printf "    rnixstrap                      — 대화형으로 새 호스트 추가 또는 기존 호스트 재설치\n"
    printf "    rnixstrap --hostname HOST       — 비대화형 (설정은 .strap.json 또는 TOML에서 로드)\n"
    printf "    rnixstrap --hostname HOST --write-only\n"
    printf "\n"
    printf "  비대화형 설정 파일:\n"
    printf "    ~/.ssh/rnixup/{hostname}.strap.json\n"
    printf '    { "ip": "1.2.3.4", "sshKey": "~/.ssh/key.pem", "sshUser": "root",\n'
    printf '      "system": "x86_64-linux", "bootLoader": "grub-uefi",\n'
    printf '      "diskDevice": "/dev/vda", "services": ["caddy", "docker"] }\n'
    printf "\n"
    printf "  흐름:\n"
    printf "    새 호스트:    공급자/IP/키/서비스 입력 → 설정 확인 → 선택\n"
    printf "    기존 호스트:  목록에서 선택 → IP/키 확인 → 설정 확인 → 선택\n"
    printf "\n"
    printf "  선택지:\n"
    printf "    바로 진행  nixos-anywhere 설치 + deploy-rs 배포\n"
    printf "    쓰기만     파일만 생성/갱신하고 종료 (.nix 편집 후 재실행)\n"
    printf "    취소       아무것도 하지 않고 종료\n"
    printf "\n"
    printf "  설정 변경 배포(재설치 아님)는 'rnixup'을 사용하세요.\n"
    printf "\n"
    exit 0
fi

# ── 파라미터 파싱 ─────────────────────────────────────────────────────────────
_RNIXSTRAP_HOSTNAME_ARG=""
_RNIXSTRAP_WRITE_ONLY_ARG=false

while [ $# -gt 0 ]; do
    case "$1" in
        --hostname)  _RNIXSTRAP_HOSTNAME_ARG="$2"; shift 2 ;;
        --write-only) _RNIXSTRAP_WRITE_ONLY_ARG=true; shift ;;
        --help|-h) ;; # 위에서 처리됨
        *) log_msg "Error" "알 수 없는 옵션: $1  (도움말: rnixstrap --help)"; exit 1 ;;
    esac
done

# ── 상수 ──────────────────────────────────────────────────────────────────────
BUILD_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/nixos/build"
JSON_DIR="/tmp/nixup-json"
ENV_FILE="$NIXOS_PATH/.env"
mkdir -p "$JSON_DIR"

# ── 공유 상태 (Phase 1 → Phase 2 전달) ───────────────────────────────────────
_HOST_IS_NEW=true       # false = 기존 호스트 (재설치 or standalone bootstrap)
_HOST_HAS_DEPLOY=true   # false = [deploy] 섹션 없는 기존 호스트 (standalone bootstrap)
_HOSTNAME=""
_IP=""
_SSH_KEY=""
_SYSTEM="x86_64-linux"
_BOOT_LOADER=""
_DISK_DEVICE=""
_REMOTE_RAM_MB=-1   # 원격 RAM(MB), -1=감지 전/실패
_SERVICES=()
# 서버 서비스 목록: 형식 "id" "UI 레이블" (짝수=id, 홀수=설명)
# ask_services(lib-input.sh)와 generate_toml(task-setup.sh)이 공유
_ALL_SERVICES=(
    "caddy"           "caddy            Caddy 웹서버 / 리버스 프록시"
    "tailscale"       "tailscale        Tailscale VPN 클라이언트"
    "docker"          "docker           Docker 컨테이너 런타임"
    "nix-cache-proxy" "nix-cache-proxy  Nix 바이너리 캐시 프록시"
)
_WRITE_ONLY=false       # true = 파일 작업만 하고 설치 없이 종료
_SSH_USER="root"        # nixos-anywhere bootstrap 접속 유저
_SSH_PASS=""            # 비밀번호 인증 시 설정 (키 인증이면 비움)
_TOML_IP=""             # 기존 호스트 TOML에서 로드 ([deploy] 있는 경우)
_TOML_SSH_KEY=""        # 기존 호스트 TOML에서 로드 ([deploy] 있는 경우)
_TOML_SSH_USER=""       # 기존 호스트 TOML에서 로드 ([deploy].sshUser)
_TOML_CLOUD=""          # 기존 호스트 TOML에서 로드 (cloud = "aws" 등, 없으면 "")
_TOML_BOOT_LOADER=""    # 기존 호스트 TOML에서 로드
_TOML_DISK_DEVICE=""    # 기존 호스트 TOML에서 로드
_BOOTSTRAP_IP=""        # .bootstrap.env에서 로드 (standalone 기본값)
_BOOTSTRAP_SSH_KEY=""   # .bootstrap.env에서 로드 (standalone 기본값)
_BOOTSTRAP_SSH_USER=""  # .bootstrap.env에서 로드 (standalone 기본값)

# ── lib 로드 ──────────────────────────────────────────────────────────────────
source "$SCRIPT_DIR/lib-build.sh"
source "$SCRIPT_DIR/rnixup.lib-secrets.sh"
source "$SCRIPT_DIR/rnixstrap.lib-input.sh"
source "$SCRIPT_DIR/rnixstrap.task-setup.sh"

# ── Cleanup trap ──────────────────────────────────────────────────────────────
_cleanup() {
    _print_summary
    tput cnorm 2>/dev/null || true
    stty sane 2>/dev/null || true
}
trap '_cleanup' EXIT
trap '_cleanup; exit 130' INT TERM

# ── 시작 배너 ─────────────────────────────────────────────────────────────────
printf "\n"
log_msg "Init" "원격 NixOS 호스트 초기 설치 도구"
log_msg "Init" "새 호스트 추가 또는 기존 호스트 재설치를 진행합니다."
printf "\n"

# ── 비대화형 모드 ─────────────────────────────────────────────────────────────
if [[ -n "$_RNIXSTRAP_HOSTNAME_ARG" ]]; then
    _HOSTNAME="$_RNIXSTRAP_HOSTNAME_ARG"
    [ "$_RNIXSTRAP_WRITE_ONLY_ARG" = true ] && _WRITE_ONLY=true

    # strap.json 로드 (존재하면)
    _strap_json="$HOME/.ssh/rnixup/${_HOSTNAME}.strap.json"
    if [ -f "$_strap_json" ]; then
        log_msg "Init" "strap.json 로드: $_strap_json"
        _j_ip=$(jq -r '.ip // empty'          "$_strap_json")
        _j_key=$(jq -r '.sshKey // empty'     "$_strap_json")
        _j_user=$(jq -r '.sshUser // empty'   "$_strap_json")
        _j_pass=$(jq -r '.sshPass // empty'   "$_strap_json")
        _j_system=$(jq -r '.system // empty'  "$_strap_json")
        _j_boot=$(jq -r '.bootLoader // empty' "$_strap_json")
        _j_disk=$(jq -r '.diskDevice // empty' "$_strap_json")
        _j_wo=$(jq -r '.writeOnly // empty'   "$_strap_json")
        mapfile -t _j_services < <(jq -r '.services // [] | .[]' "$_strap_json")

        [[ -n "$_j_ip"     ]] && _IP="$_j_ip"
        [[ -n "$_j_key"    ]] && _SSH_KEY="${_j_key/#\~/$HOME}"
        [[ -n "$_j_user"   ]] && _SSH_USER="$_j_user"
        [[ -n "$_j_pass"   ]] && _SSH_PASS="$_j_pass"
        [[ -n "$_j_system" ]] && _SYSTEM="$_j_system"
        [[ -n "$_j_boot"   ]] && _BOOT_LOADER="$_j_boot"
        [[ -n "$_j_disk"   ]] && _DISK_DEVICE="$_j_disk"
        [[ "$_j_wo" == "true" ]] && _WRITE_ONLY=true
        [ "${#_j_services[@]}" -gt 0 ] && _SERVICES=("${_j_services[@]}")

        # services 유효성 검사
        for _svc in "${_SERVICES[@]}"; do
            _valid=false
            for (( _i=0; _i<${#_ALL_SERVICES[@]}; _i+=2 )); do
                [[ "${_ALL_SERVICES[$_i]}" == "$_svc" ]] && _valid=true && break
            done
            [[ "$_valid" == false ]] && {
                log_msg "Error" "알 수 없는 서비스: $_svc (허용: caddy tailscale docker nix-cache-proxy)"
                exit 1
            }
        done
    fi

    # TOML 존재 여부로 host 타입 결정
    _toml_path="$NIXOS_PATH/hosts/${_HOSTNAME}.toml"
    if [ -f "$_toml_path" ]; then
        if grep -q '^\[deploy\]' "$_toml_path" 2>/dev/null; then
            # 기존 deploy 호스트
            _HOST_IS_NEW=false
            _HOST_HAS_DEPLOY=true
            _load_toml_values  # _TOML_IP, _TOML_SSH_KEY, _TOML_SSH_USER 등 설정
            # TOML 기본값을 strap.json/args보다 낮은 우선순위로 적용
            [[ -z "$_IP"       ]] && _IP="$_TOML_IP"
            [[ -z "$_SSH_KEY"  ]] && _SSH_KEY="${_TOML_SSH_KEY/#\~/$HOME}"
            [[ -z "$_SSH_USER" || "$_SSH_USER" == "root" ]] && \
                [[ -n "$_TOML_SSH_USER" ]] && _SSH_USER="$_TOML_SSH_USER"
            [ -n "$_TOML_CLOUD" ] && [ -n "$_TOML_SSH_USER" ] && _SSH_USER="$_TOML_SSH_USER"
            log_msg "Done" "기존 호스트 (재설치): $_HOSTNAME"
        else
            # standalone 호스트
            _HOST_IS_NEW=false
            _HOST_HAS_DEPLOY=false
            _load_toml_type
            load_bootstrap_env
            [[ -z "$_IP"      ]] && _IP="$_BOOTSTRAP_IP"
            [[ -z "$_SSH_KEY" ]] && _SSH_KEY="${_BOOTSTRAP_SSH_KEY/#\~/$HOME}"
            [[ -z "$_SSH_USER" || "$_SSH_USER" == "root" ]] && \
                [[ -n "$_BOOTSTRAP_SSH_USER" ]] && _SSH_USER="$_BOOTSTRAP_SSH_USER"
            log_msg "Done" "기존 호스트 (standalone bootstrap): $_HOSTNAME"
        fi
    else
        # 신규 호스트
        _HOST_IS_NEW=true
        _HOST_HAS_DEPLOY=true
        [[ -z "$_IP" ]] && {
            log_msg "Error" "신규 호스트 '$_HOSTNAME': ip 필수 (strap.json에 \"ip\" 추가)"
            exit 1
        }
        [[ -z "$_SSH_KEY" && -z "$_SSH_PASS" ]] && {
            log_msg "Error" "신규 호스트 '$_HOSTNAME': sshKey 또는 sshPass 필수"
            exit 1
        }
        log_msg "Done" "신규 호스트: $_HOSTNAME"
    fi

    export RNIXSTRAP_NONINTERACTIVE=1
    log_msg "Notice" "비대화형 모드: hostname=$_HOSTNAME ip=$_IP user=$_SSH_USER"
    run_setup
    exit 0
fi

# ── Phase 1: 대화형 입력 수집 ─────────────────────────────────────────────────
select_or_create_hostname

if [ "$_HOST_IS_NEW" = true ]; then
    ask_ssh_user
    ask_ip
    ask_ssh_auth
    ask_system
    ask_services
elif [ "$_HOST_HAS_DEPLOY" = false ]; then
    load_bootstrap_env  # ~/.ssh/rnixup/<hostname>.bootstrap.env → _BOOTSTRAP_* 변수
    ask_ssh_user        # _BOOTSTRAP_SSH_USER 기본값
    ask_ip              # _BOOTSTRAP_IP 기본값
    ask_ssh_auth        # _BOOTSTRAP_SSH_KEY 기본값
else
    # cloud 호스트(AWS 등)는 TOML sshUser가 부트스트랩 유저이기도 함 (ec2-user 등)
    # VPS/bare-metal은 root가 부트스트랩 유저 — deploy-rs는 resolved.json에서 독립적으로 읽음
    [ -n "$_TOML_CLOUD" ] && [ -n "$_TOML_SSH_USER" ] && _SSH_USER="$_TOML_SSH_USER"
    ask_ip        # 기존 TOML IP를 기본값으로, 변경 가능
    ask_ssh_key   # 기존 TOML 키를 기본값으로, 변경 가능
fi

run_setup
