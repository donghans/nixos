#!/usr/bin/env nix-shell
#!nix-shell -i bash -p nh jq nix-output-monitor git

# 1. 라이브러리 로드 (같은 폴더 내에 위치함)
SCRIPT_DIR=$(dirname $(readlink -f "$0"))
NIXOS_PATH=$(readlink -f "$SCRIPT_DIR/../..")

source "$SCRIPT_DIR/nhw.lib-build.sh"
source "$SCRIPT_DIR/nhw.lib-lock.sh"

acquire_lock

# 2. 환경 및 설정 로드
ENV_FILE="$NIXOS_PATH/.env"
[ -f "$ENV_FILE" ] && { set -a; source "$ENV_FILE"; set +a; }
STABLE_LOCKS_DIR="$NIXOS_PATH/.locks"

cleanup() {
    echo "[nhw] Cleaning up..."
    # fix-unstable의 경우 HOST_SPECIFIC_LOCK이 설정되지 않았을 수 있으므로 체크
    [ -n "$HOST_SPECIFIC_LOCK" ] && finalize_lock_sync "$LOCK_CHANGED" "$HOST_SPECIFIC_LOCK"
}
trap cleanup EXIT

# 3. 인자 분석
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

# 3-1. Clean 특수 처리
if [ "$DO_CLEAN" = true ]; then
    [ "$CLEAN_TARGET" = "all" ] && sudo nh clean all --keep 3 || nh clean "$CLEAN_TARGET" --keep 3
    exit 0
fi

# 3-2. Fix-unstable 특수 처리
if [ "$SCOPE" == "fix-unstable" ]; then
    source "$SCRIPT_DIR/nhw.task-fix.sh"
    exit 0
fi

# 4. Host 정보 결정 (lib-build.sh 함수 활용)
read -r HOST_ID IS_ROLLING <<< "$(determine_host_info "$SCOPE" "$HOST_ARG" "$ENV_FILE" "$NIXOS_PATH/dev/_info.json")"
[ $? -ne 0 ] && exit 1

# 5. Lock 파일 경로 결정 및 빌드 디렉토리 준비
TARGET_LOCK="$TMP_BUILD_DIR/flake.lock"
[ "$IS_ROLLING" == "true" ] && HOST_SPECIFIC_LOCK="$STABLE_LOCKS_DIR/_rolling.lock" || HOST_SPECIFIC_LOCK="$STABLE_LOCKS_DIR/$HOST_ID.lock"

prepare_build_dir "$NIXOS_PATH" "$TMP_BUILD_DIR" "$ENV_FILE"

# 6. 실행 (Dispatcher)
if [ "$ACTION" == "update" ]; then
    source "$SCRIPT_DIR/nhw.task-update.sh"
else
    # Lock 전략 적용
    apply_lock_strategy "$IS_ROLLING" "$HOST_SPECIFIC_LOCK" "$TARGET_LOCK" "$STABLE_LOCKS_DIR" "$TMP_BUILD_DIR"

    # 태스크 분기
    if [ "$SCOPE" == "iso" ]; then
        source "$SCRIPT_DIR/nhw.task-iso.sh"
    else
        source "$SCRIPT_DIR/nhw.task-nh.sh"
    fi
fi
