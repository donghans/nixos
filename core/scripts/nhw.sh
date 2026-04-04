#!/usr/bin/env nix-shell
#!nix-shell -i bash -p nh jq nix-output-monitor git

# 1. Initialization
START_TIME_RAW=$(date +%s)
START_TIME_STR=$(date "+%Y-%m-%d %H:%M:%S")
SCRIPT_DIR=$(dirname $(readlink -f "$0"))
NIXOS_PATH=$(readlink -f "$SCRIPT_DIR/../..")

source "$SCRIPT_DIR/nhw.lib-build.sh"
source "$SCRIPT_DIR/nhw.lib-lock.sh"

# 2. Init Messages
log_msg "Init" "NHW: [NixOS Helper](https://github.com/viperML/nh) Wrapper"

# .env Load
ENV_FILE="$NIXOS_PATH/.env"
[ -f "$ENV_FILE" ] && { set -a; source "$ENV_FILE"; set +a; }

# Logging Setup (YYYYMMDDTHHMMSS.log format)
LOG_TIMESTAMP=$(date +%Y%m%dT%H%M%S)
setup_logging "$LOG_TIMESTAMP"

acquire_lock

cleanup() {
    END_TIME_RAW=$(date +%s)
    END_TIME_STR=$(date "+%Y-%m-%d %H:%M:%S")
    DURATION=$((END_TIME_RAW - START_TIME_RAW))
    
    # 📊 Summary
    log_msg "Summary" "Started:  $START_TIME_STR"
    log_msg "Summary" "Finished: $END_TIME_STR"
    log_msg "Summary" "Duration: ${DURATION}s"
    log_msg "Summary" "Log File: ${LOG_FILE:-disabled}"

    check_origin_git_status "$NIXOS_PATH"
    [ -n "$HOST_SPECIFIC_LOCK" ] && finalize_lock_sync "$LOCK_CHANGED" "$HOST_SPECIFIC_LOCK"
    
    rotate_logs
}
trap cleanup EXIT

# 3. Argument Parsing
DO_CLEAN=false; CLEAN_TARGET="user"; HOST_ARG=""; SCOPE="home"; ACTION="switch"; LOCK_CHANGED=false
EXTRA_ARGS=()

for arg in "$@"; do
    case $arg in
        clean) DO_CLEAN=true ;;
        all) CLEAN_TARGET="all" ;;
        os|home|iso|fix-unstable) SCOPE="$arg" ;;
        switch|boot|test|update) ACTION="$arg" ;;
        *) 
            if [ "$SCOPE" == "fix-unstable" ]; then
                EXTRA_ARGS+=("$arg")
            else
                HOST_ARG="$arg"
            fi
            ;;
    esac
done

# 4. Routing
if [ "$DO_CLEAN" = true ]; then
    log_msg "Init" "Action:   cleanup"
    log_exec "nh" ">"
    [ "$CLEAN_TARGET" = "all" ] && sudo nh clean all --keep 3 || nh clean "$CLEAN_TARGET" --keep 3
    log_exec "nh" "<"
    exit 0
fi

if [ "$SCOPE" == "fix-unstable" ]; then
    log_msg "Init" "Action:   fix-unstable"
    source "$SCRIPT_DIR/nhw.task-fix.sh"
    exit 0
fi

# Determine Host
STABLE_LOCKS_DIR="$NIXOS_PATH/.locks"
read -r HOST_ID IS_ROLLING <<< "$(determine_host_info "$SCOPE" "$HOST_ARG" "$ENV_FILE" "$NIXOS_PATH/dev/_info.json")"
[ $? -ne 0 ] && exit 1

TARGET_LOCK="$TMP_BUILD_DIR/flake.lock"
[ "$IS_ROLLING" == "true" ] && HOST_SPECIFIC_LOCK="$STABLE_LOCKS_DIR/_rolling.lock" || HOST_SPECIFIC_LOCK="$STABLE_LOCKS_DIR/$HOST_ID.lock"

# Print Configuration Info
log_msg "Init" "Action:   $SCOPE $ACTION"
log_msg "Init" "Target:   $HOST_ID"
log_msg "Init" "Mode:     $([ "$IS_ROLLING" == "true" ] && echo "rolling" || echo "stable")"

# 5. Execution
prepare_build_dir "$NIXOS_PATH" "$TMP_BUILD_DIR" "$ENV_FILE"

if [ "$ACTION" == "update" ]; then
    source "$SCRIPT_DIR/nhw.task-update.sh"
else
    apply_lock_strategy "$IS_ROLLING" "$HOST_SPECIFIC_LOCK" "$TARGET_LOCK" "$STABLE_LOCKS_DIR" "$TMP_BUILD_DIR"
    if [ "$SCOPE" == "iso" ]; then
        source "$SCRIPT_DIR/nhw.task-iso.sh"
    else
        source "$SCRIPT_DIR/nhw.task-nh.sh"
    fi
fi
