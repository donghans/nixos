#!/usr/bin/env nix-shell
#!nix-shell -i bash -I nixpkgs=flake:nixpkgs -p nvd jq nix-output-monitor git gh dotenv-cli deadnix statix alejandra shellcheck python3
# shellcheck disable=SC1008,SC1091,SC2034
set -euo pipefail

# 1. Initialization
START_TIME_RAW=$(date +%s)
START_TIME_STR=$(date "+%Y-%m-%d %H:%M:%S")
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
NIXOS_PATH=$(readlink -f "$SCRIPT_DIR/../..")

# .env Load (dotenv-cli를 활용한 RCE 안전 환경 재귀 호출)
ENV_FILE="$NIXOS_PATH/.env"
if [ -f "$ENV_FILE" ] && [ -z "${NIXUP_DOTENV_LOADED:-}" ]; then
    export NIXUP_DOTENV_LOADED=1
    exec dotenv -e "$ENV_FILE" -- "$0" "$@"
fi

source "$SCRIPT_DIR/nixup.lib-build.sh"
source "$SCRIPT_DIR/nixup.lib-lock.sh"
source "$SCRIPT_DIR/nixup.lib-help.sh"
_nixup_maybe_help "$@"

# 2. Argument Parsing
DO_CLEAN=false; CLEAN_TARGET="user"; CLEAN_KEEP=3
TARGET_PROFILE="os"; ACTION="switch"; LOCK_CHANGED=false
ISO_ARCH="x86_64"
# shellcheck disable=SC2034  # sourced scripts (nixup.task-check.sh) 에서 사용
CHECK_DEEP=false
EXTRA_ARGS=()

# 서브커맨드 파싱 (첫 번째 인자)
SUBCOMMAND="${1:-}"
case "$SUBCOMMAND" in
    os|home|check|fix|iso|update|clean)
        TARGET_PROFILE="$SUBCOMMAND"
        shift
        ;;
    "")
        TARGET_PROFILE="os"
        ;;
    -*)
        # 플래그만 → os 기본
        TARGET_PROFILE="os"
        ;;
    *)
        log_msg "Error" "unknown subcommand: '$SUBCOMMAND'. use: os home check fix iso update clean"
        exit 1
        ;;
esac

[ "$TARGET_PROFILE" = "fix" ]   && TARGET_PROFILE="fix-unstable"
[ "$TARGET_PROFILE" = "clean" ] && DO_CLEAN=true

for arg in "$@"; do
    case $arg in
        --all|-a)       CLEAN_TARGET="all" ;;
        --arm)          ISO_ARCH="aarch64" ;;
        --deep)
            # shellcheck disable=SC2034
            CHECK_DEEP=true ;;
        -t|--activate)  ACTION="test" ;;
        -n|--next-boot) ACTION="boot" ;;
        -d|--dry-run)   ACTION="build" ;;
        --keep=*)       CLEAN_KEEP="${arg#--keep=}" ;;
        --help|-h)      print_help_subcmd "$TARGET_PROFILE"; exit 0 ;;
        -*)
            log_msg "Error" "unknown flag: $arg"
            exit 1 ;;
        *)
            if [ "$TARGET_PROFILE" = "fix-unstable" ]; then
                EXTRA_ARGS+=("$arg")
            else
                log_msg "Error" "unknown argument: '$arg'"
                exit 1
            fi
            ;;
    esac
done

# 3. Logging & Lock
exec 3>&1
LOG_TIMESTAMP=$(date +%Y%m%dT%H%M%S)
setup_logging "$(resolve_log_name)"
acquire_lock

# 4. Resolve & Host Detection
mkdir -p "$JSON_DIR"
python3 -B "$SCRIPT_DIR/nixup.resolve.py" "$NIXOS_PATH" "$JSON_DIR" >/dev/null

LOCK_STORE_DIR="$NIXOS_PATH/.locks"
HOST_ID=""; IS_ROLLING=""; HOST_SPECIFIC_LOCK=""
if [ "$DO_CLEAN" != true ] && [ "$TARGET_PROFILE" != "fix-unstable" ]; then
    _PERSIST_ENV=""
    if [[ "$TARGET_PROFILE" != "check" && "$TARGET_PROFILE" != "update" && ( "$ACTION" == "switch" || "$ACTION" == "test" || "$ACTION" == "boot" ) ]]; then
        _PERSIST_ENV="$ENV_FILE"
    fi
    set +e
    HOST_INFO_RAW=$(resolve_host_info "$TARGET_PROFILE" "$_PERSIST_ENV")
    DETERMINE_EXIT_CODE=$?
    set -e
    if [ $DETERMINE_EXIT_CODE -ne 0 ] || [ -z "$HOST_INFO_RAW" ]; then exit 1; fi
    read -r HOST_ID IS_ROLLING <<< "$HOST_INFO_RAW"
    HOST_SPECIFIC_LOCK="$LOCK_STORE_DIR/$( [ "$IS_ROLLING" == "true" ] && echo "_rolling.lock" || echo "$HOST_ID.lock" )"
fi

# 5. Banner & Trap
print_init_banner
IS_SUCCESS=false
trap 'handle_signal SIGINT' INT
trap 'handle_signal SIGTERM' TERM
trap cleanup EXIT

# 6. Routing
if [ "$DO_CLEAN" = true ]; then
    log_exec "nix" ">" "clean generations (keep last $CLEAN_KEEP)"

    # Home-manager 프로파일 정리 (sudo 불필요)
    HM_PROFILE="$HOME/.local/state/nix/profiles/home-manager"
    if [ -L "$HM_PROFILE" ]; then
        nix-env -p "$HM_PROFILE" --delete-generations "+${CLEAN_KEEP}" || true
    fi

    if [ "$CLEAN_TARGET" = "all" ]; then
        # 시스템 프로파일 정리 (sudo 필요)
        sudo nix-env -p /nix/var/nix/profiles/system \
            --delete-generations "+${CLEAN_KEEP}" || true
        # 시스템 전체 GC
        sudo nix-store --gc
    else
        # 사용자 영역 GC만
        nix-store --gc
    fi

    log_exec "nix" "<" "clean generations"
    IS_SUCCESS=true; exit 0
fi

if [ "$TARGET_PROFILE" == "fix-unstable" ]; then
    source "$SCRIPT_DIR/nixup.task-fix.sh"
    IS_SUCCESS=true; exit 0
fi

TARGET_LOCK="$BUILD_DIR/flake.lock"

if [ "$TARGET_PROFILE" == "check" ]; then
    source "$SCRIPT_DIR/nixup.task-check.sh"
    IS_SUCCESS=true; exit 0
fi

# 7. Execution
prepare_build_dir "$NIXOS_PATH" "$BUILD_DIR" "$ENV_FILE"

if [ "$TARGET_PROFILE" == "update" ]; then
    source "$SCRIPT_DIR/nixup.task-update.sh"
else
    apply_lock_strategy "$IS_ROLLING" "$HOST_SPECIFIC_LOCK" "$TARGET_LOCK" "$BUILD_DIR"
    if [ "$TARGET_PROFILE" == "iso" ]; then
        source "$SCRIPT_DIR/nixup.task-iso.sh"
    else
        source "$SCRIPT_DIR/nixup.task-build.sh"
    fi
fi

IS_SUCCESS=true
