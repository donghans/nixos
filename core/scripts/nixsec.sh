#!/usr/bin/env nix-shell
#!nix-shell -i bash -I nixpkgs=flake:nixpkgs -p age gh jq curl openssl sshpass
# nixsec — nix-secrets 관리 도구
# shellcheck disable=SC1008,SC1091,SC2034
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NIXOS_PATH="$(readlink -f "$SCRIPT_DIR/../..")"
JSON_DIR="${JSON_DIR:-/tmp/nixup-json}"
mkdir -p "$JSON_DIR"

source "$SCRIPT_DIR/nixup.lib-ui.sh"
_LOG_PREFIX="NIXSEC"
_START_TIME=$(date +%s)
_START_TIME_STR=$(date "+%Y-%m-%d %H:%M:%S")
trap '_print_summary' EXIT
trap 'log_msg "Error" "명령 실패 (line ${LINENO}): ${BASH_COMMAND}"' ERR

printf '\n'
log_msg "Init" "nix-secrets 관리 도구"
printf '\n'

command -v gh  &>/dev/null || { log_msg "Error" "gh CLI가 필요합니다.  nix-shell -p gh"; exit 1; }
command -v age &>/dev/null || { log_msg "Error" "age가 필요합니다.  nix-shell -p age";    exit 1; }
command -v jq  &>/dev/null || { log_msg "Error" "jq가 필요합니다.   nix-shell -p jq";     exit 1; }

# ── 서브커맨드 파싱 ───────────────────────────────────────────────────────────
# 전부 채우면 비대화형, 아무것도 없으면 대화형, 일부만 채우면 에러
# 사용법:
#   nixsec.sh upload --repo OWNER/REPO --group GROUP --remote-path PATH --file FILE
#   nixsec.sh upload --repo OWNER/REPO --group GROUP --remote-path PATH --stdin
#   nixsec.sh inject --hostname HOST [--group GROUP] [--ip IP] [--user USER] [--ssh-key PATH] [--password PW]
if [ $# -gt 0 ]; then
    _subcmd="$1"; shift
    export NIXSEC_NONINTERACTIVE=1

    while [ $# -gt 0 ]; do
        case "$1" in
            --repo)        export NIXSEC_REPO="$2";        shift 2 ;;
            --group)       export NIXSEC_GROUP="$2";       shift 2 ;;
            --remote-path) export NIXSEC_REMOTE_PATH="$2"; shift 2 ;;
            --file)        export NIXSEC_FILE="$2";        shift 2 ;;
            --stdin)       export NIXSEC_STDIN=1;          shift   ;;
            --hostname)    export NIXSEC_HOSTNAME="$2";    shift 2 ;;
            --ip)          export NIXSEC_IP="$2";          shift 2 ;;
            --user)        export NIXSEC_USER="$2";        shift 2 ;;
            --ssh-key)     export NIXSEC_SSH_KEY="$2";     shift 2 ;;
            --password)    export NIXSEC_PASSWORD="$2";    shift 2 ;;
            *) log_msg "Error" "알 수 없는 옵션: $1"
               log_msg "Notice" "사용법: nixsec.sh [upload|inject] [옵션...]"
               exit 1 ;;
        esac
    done

    printf '\n'
    case "$_subcmd" in
        upload)       source "$SCRIPT_DIR/nixsec.task-upload.sh"; _run_upload ;;
        inject)       source "$SCRIPT_DIR/nixsec.task-inject.sh"; _run_remote_inject ;;
        inject-local) source "$SCRIPT_DIR/nixsec.task-inject.sh"; _run_local_apply ;;
        *) log_msg "Error" "알 수 없는 서브커맨드: $_subcmd"
           log_msg "Notice" "지원 서브커맨드: upload, inject, inject-local"
           exit 1 ;;
    esac
    exit 0
fi

# ── 대화형 메뉴 ───────────────────────────────────────────────────────────────
_pick "작업을 선택하세요:" \
    "새 레포 초기화         — age 키 생성 + GitHub 프라이빗 레포 생성" \
    "시크릿 업로드          — 파일을 age 암호화해서 레포에 추가/갱신" \
    "원격 호스트에 주입     — 워크스테이션에서 복호화 후 SSH 전송" \
    "이 워크스테이션에 적용 — secrets.json 기반으로 로컬에 복호화 배치" \
    "age 키 복구            — 새 워크스테이션에서 키 경로 등록"

printf '\n'
case "$REPLY" in
    0) source "$SCRIPT_DIR/nixsec.task-init.sh";   _run_init ;;
    1) source "$SCRIPT_DIR/nixsec.task-upload.sh"; _run_upload ;;
    2) source "$SCRIPT_DIR/nixsec.task-inject.sh"; _run_remote_inject ;;
    3) source "$SCRIPT_DIR/nixsec.task-inject.sh"; _run_local_apply ;;
    4) source "$SCRIPT_DIR/nixsec.task-inject.sh"; _run_key_restore ;;
esac
