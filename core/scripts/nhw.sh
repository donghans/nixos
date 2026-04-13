#!/usr/bin/env nix-shell
#!nix-shell -i bash -p nh nvd jq nix-output-monitor git gh dotenv-cli deadnix statix alejandra shellcheck python3
# shellcheck disable=SC1008,SC1091,SC2034
set -euo pipefail

# 1. Initialization
START_TIME_RAW=$(date +%s)
START_TIME_STR=$(date "+%Y-%m-%d %H:%M:%S")
SCRIPT_DIR=$(dirname "$(readlink -f "$0")")
NIXOS_PATH=$(readlink -f "$SCRIPT_DIR/../..")

# .env Load (dotenv-cli를 활용한 RCE 안전 환경 재귀 호출)
ENV_FILE="$NIXOS_PATH/.env"
if [ -f "$ENV_FILE" ] && [ -z "${NHW_DOTENV_LOADED:-}" ]; then
    export NHW_DOTENV_LOADED=1
    exec dotenv -e "$ENV_FILE" -- "$0" "${@:-}"
fi

source "$SCRIPT_DIR/nhw.lib-build.sh"
source "$SCRIPT_DIR/nhw.lib-lock.sh"

# 2. Argument Parsing
DO_CLEAN=false; CLEAN_TARGET="user"; TARGET_HOST=""; TARGET_PROFILE="home"; ACTION="switch"; LOCK_CHANGED=false
ISO_ARCH="x86_64"
# shellcheck disable=SC2034  # sourced scripts (nhw.task-check.sh) 에서 사용
CHECK_DEEP=false
EXTRA_ARGS=()

for arg in "${@:-}"; do
    case $arg in
        clean) DO_CLEAN=true ;;
        all) CLEAN_TARGET="all" ;;
        arm) ISO_ARCH="aarch64" ;;
        os|home|iso|fix-unstable|check) TARGET_PROFILE="$arg" ;;
        switch|boot|test|build|update) ACTION="$arg" ;;
        --deep|deep)
            # shellcheck disable=SC2034
            CHECK_DEEP=true ;;
        *)
            if [ "$TARGET_PROFILE" == "fix-unstable" ]; then
                EXTRA_ARGS+=("$arg")
            else
                TARGET_HOST="$arg"
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
python3 -B "$SCRIPT_DIR/nhw.resolve.py" "$NIXOS_PATH" "$JSON_DIR" >/dev/null

LOCK_STORE_DIR="$NIXOS_PATH/.locks"
HOST_ID=""; IS_ROLLING=""; HOST_SPECIFIC_LOCK=""
if [ "$DO_CLEAN" != true ] && [ "$TARGET_PROFILE" != "fix-unstable" ]; then
    _PERSIST_ENV=""
    if [[ "$TARGET_PROFILE" != "check" && ( "$ACTION" == "switch" || "$ACTION" == "test" || "$ACTION" == "boot" ) ]]; then
        _PERSIST_ENV="$ENV_FILE"
    fi
    set +e
    HOST_INFO_RAW=$(determine_host_info "$TARGET_PROFILE" "$TARGET_HOST" "$_PERSIST_ENV")
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
    log_exec "nh" ">" "nh clean $CLEAN_TARGET"
    if [ "$CLEAN_TARGET" = "all" ]; then
        sudo nh clean all --keep 3 || true
    else
        nh clean "$CLEAN_TARGET" --keep 3 || true
    fi
    log_exec "nh" "<" "nh clean $CLEAN_TARGET"
    IS_SUCCESS=true; exit 0
fi

if [ "$TARGET_PROFILE" == "fix-unstable" ]; then
    source "$SCRIPT_DIR/nhw.task-fix.sh"
    IS_SUCCESS=true; exit 0
fi

TARGET_LOCK="$BUILD_DIR/flake.lock"

if [ "$TARGET_PROFILE" == "check" ]; then
    source "$SCRIPT_DIR/nhw.task-check.sh"
    IS_SUCCESS=true; exit 0
fi

# 7. Execution
prepare_build_dir "$NIXOS_PATH" "$BUILD_DIR" "$ENV_FILE"

if [ "$ACTION" == "update" ]; then
    source "$SCRIPT_DIR/nhw.task-update.sh"
else
    apply_lock_strategy "$IS_ROLLING" "$HOST_SPECIFIC_LOCK" "$TARGET_LOCK" "$BUILD_DIR"
    if [ "$TARGET_PROFILE" == "iso" ]; then
        source "$SCRIPT_DIR/nhw.task-iso.sh"
    else
        source "$SCRIPT_DIR/nhw.task-nh.sh"
    fi
fi

IS_SUCCESS=true
