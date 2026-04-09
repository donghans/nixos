#!/usr/bin/env nix-shell
#!nix-shell -i bash -p nh nvd jq nix-output-monitor git dotenv-cli deadnix statix alejandra shellcheck
# shellcheck disable=SC1008,SC1091
set -euo pipefail

# 1. Initialization & Argument Parsing
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

# 2. Logging Setup
# fd 3: 원본 터미널 stdout 보존 (setup_logging의 exec 리디렉션 이전에 저장)
# nhw.task-nh.sh에서 nom 출력을 로그 파이프가 아닌 실제 터미널로 보낼 때 사용
exec 3>&1
LOG_TIMESTAMP=$(date +%Y%m%dT%H%M%S)
if [ "$DO_CLEAN" = true ]; then
    setup_logging "${LOG_TIMESTAMP}-clean-${CLEAN_TARGET}"
elif [[ "$TARGET_PROFILE" =~ ^(check|fix-unstable|iso)$ ]]; then
    if [ "$TARGET_PROFILE" = "iso" ]; then
        setup_logging "${LOG_TIMESTAMP}-iso-${ISO_ARCH}"
    else
        setup_logging "${LOG_TIMESTAMP}-${TARGET_PROFILE}"
    fi
else
    setup_logging "${LOG_TIMESTAMP}-${TARGET_PROFILE}-${ACTION}"
fi

acquire_lock

# Resolver: JSON_DIR에 resolved.json + presets.json 생성 (determine_host_info가 읽음)
# Init 블록보다 먼저 실행하여 호스트 정보를 확보 (출력은 Init 이후에 표시)
mkdir -p "$JSON_DIR"
python3 "$SCRIPT_DIR/nhw.resolve.py" "$NIXOS_PATH" "$JSON_DIR" >/dev/null

# Host 결정 (clean/fix-unstable은 불필요)
LOCK_STORE_DIR="$NIXOS_PATH/.locks"
HOST_ID=""; IS_ROLLING=""; HOST_SPECIFIC_LOCK=""
if [ "$DO_CLEAN" != true ] && [ "$TARGET_PROFILE" != "fix-unstable" ]; then
    set +e
    HOST_INFO_RAW=$(determine_host_info "$TARGET_PROFILE" "$TARGET_HOST" "$ENV_FILE")
    DETERMINE_EXIT_CODE=$?
    set -e
    if [ $DETERMINE_EXIT_CODE -ne 0 ] || [ -z "$HOST_INFO_RAW" ]; then exit 1; fi
    read -r HOST_ID IS_ROLLING <<< "$HOST_INFO_RAW"
    if [ "$IS_ROLLING" == "true" ]; then
        HOST_SPECIFIC_LOCK="$LOCK_STORE_DIR/_rolling.lock"
    else
        HOST_SPECIFIC_LOCK="$LOCK_STORE_DIR/$HOST_ID.lock"
    fi
fi

# 3. Init Block (배너 + Action/Target/Mode 를 최상단에 표시)
log_msg "Init" "NHW: [NixOS Helper](https://github.com/viperML/nh) Wrapper"

# Action 레이블
if [ "$DO_CLEAN" = true ]; then
    log_msg "Init" "Action:   cleanup"
elif [ "$TARGET_PROFILE" = "fix-unstable" ]; then
    log_msg "Init" "Action:   fix-unstable"
elif [ "$TARGET_PROFILE" = "check" ] && [ "$CHECK_DEEP" = true ]; then
    log_msg "Init" "Action:   check --deep"
elif [[ "$TARGET_PROFILE" =~ ^(check|iso)$ ]]; then
    if [ "$TARGET_PROFILE" = "iso" ]; then
        log_msg "Init" "Action:   iso [${ISO_ARCH}]"
    else
        log_msg "Init" "Action:   $TARGET_PROFILE"
    fi
else
    log_msg "Init" "Action:   $TARGET_PROFILE $ACTION"
fi

# Target: 특정 호스트에 종속된 작업에만 표시
# 숨김: clean, fix-unstable, iso, check --deep
if [ -n "$HOST_ID" ] && [ "$TARGET_PROFILE" != "iso" ] && ! { [ "$TARGET_PROFILE" = "check" ] && [ "$CHECK_DEEP" = true ]; }; then
    log_msg "Init" "Target:   $HOST_ID"
    if [ "$IS_ROLLING" == "true" ]; then
        log_msg "Init" "Mode:     rolling"
    else
        log_msg "Init" "Mode:     stable"
    fi
fi

# 4. Advanced Trap & State Management
IS_SUCCESS=false

handle_signal() {
    local sig="${1:-UNKNOWN}"
    log_msg "Error" "Process interrupted by user. ($sig)"
    exit 130
}

trap 'handle_signal SIGINT' INT
trap 'handle_signal SIGTERM' TERM

cleanup() {
    END_TIME_RAW=$(date +%s)
    END_TIME_STR=$(date "+%Y-%m-%d %H:%M:%S")
    DURATION=$((END_TIME_RAW - START_TIME_RAW))

    if [ "$IS_SUCCESS" != true ]; then
        log_msg "Error" "Process terminated abnormally. Removing temporary build reference."
        [ -L "$NIXOS_PATH/.build" ] && rm -f "$NIXOS_PATH/.build" || true
    fi

    # 📊 Summary
    log_msg "Summary" "Started:  $START_TIME_STR"
    log_msg "Summary" "Finished: $END_TIME_STR"
    log_msg "Summary" "Duration: ${DURATION}s"
    log_msg "Summary" "Log File: ${LOG_FILE:-disabled}"

    check_origin_git_status "$NIXOS_PATH"
    if [ -n "${HOST_SPECIFIC_LOCK:-}" ]; then
        finalize_lock_sync "$LOCK_CHANGED" "$HOST_SPECIFIC_LOCK"
    fi

    rotate_logs
}
trap cleanup EXIT

# 5. Routing
if [ "$DO_CLEAN" = true ]; then
    log_exec "nh" ">" "nh clean $CLEAN_TARGET"
    if [ "$CLEAN_TARGET" = "all" ]; then
        sudo nh clean all --keep 3 || true
    else
        nh clean "$CLEAN_TARGET" --keep 3 || true
    fi
    log_exec "nh" "<" "nh clean $CLEAN_TARGET"
    IS_SUCCESS=true
    exit 0
fi

if [ "$TARGET_PROFILE" == "fix-unstable" ]; then
    source "$SCRIPT_DIR/nhw.task-fix.sh"
    IS_SUCCESS=true
    exit 0
fi

TARGET_LOCK="$TMP_BUILD_DIR/flake.lock"

if [ "$TARGET_PROFILE" == "check" ]; then
    source "$SCRIPT_DIR/nhw.task-check.sh"
    IS_SUCCESS=true
    exit 0
fi

# 6. Execution
prepare_build_dir "$NIXOS_PATH" "$TMP_BUILD_DIR" "$ENV_FILE"

if [ "$ACTION" == "update" ]; then
    source "$SCRIPT_DIR/nhw.task-update.sh"
else
    apply_lock_strategy "$IS_ROLLING" "$HOST_SPECIFIC_LOCK" "$TARGET_LOCK" "$LOCK_STORE_DIR" "$TMP_BUILD_DIR"
    if [ "$TARGET_PROFILE" == "iso" ]; then
        source "$SCRIPT_DIR/nhw.task-iso.sh"
    else
        source "$SCRIPT_DIR/nhw.task-nh.sh"
    fi
fi

# 모든 과정이 문제없이 완료됨
IS_SUCCESS=true
