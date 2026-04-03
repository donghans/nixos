#!/usr/bin/env nix-shell
#!nix-shell -i bash -p nh jq

# 1. 경로 설정 및 상수
NIXOS_PATH=$(dirname $(readlink -f "$0"))
GIT="git -C $NIXOS_PATH"

ID_FILE="$NIXOS_PATH/.current_host"
LOCK_FILE_PTR="$NIXOS_PATH/.current_lock"
FLAKE_DIR="$NIXOS_PATH/_flakes"
TARGET_LOCK="$FLAKE_DIR/flake.lock"

# 모든 락 파일은 루트의 .locks 디렉토리에서 관리됩니다.
LOCKS_DIR="$NIXOS_PATH/.locks/rolling"
STABLE_LOCKS_DIR="$NIXOS_PATH/.locks"

NH_TARGET="$FLAKE_DIR"

ITEMS=(
    "dev:../dev:dir"
    "lib:../lib:dir"
)

cleanup() {
    echo "🧹 Cleaning up temporary links and lock..."
    for item in "${ITEMS[@]}"; do
        IFS=':' read -r name src type <<< "$item"
        TARGET_PATH="${FLAKE_DIR}/${name}"
        if [ -e "$TARGET_PATH" ] || [ -L "$TARGET_PATH" ]; then
            rm -rf "$TARGET_PATH"
            $GIT rm --cached "$TARGET_PATH" > /dev/null 2>&1
        fi
    done

    if [ -f "$TARGET_LOCK" ]; then
        rm -f "$TARGET_LOCK"
        $GIT rm --cached "$TARGET_LOCK" > /dev/null 2>&1
    fi
}

setup_links() {
    echo "🔗 Preparing build environment (linking dev/lib)..."
    for item in "${ITEMS[@]}"; do
        IFS=':' read -r name src type <<< "$item"
        TARGET_PATH="${FLAKE_DIR}/${name}"
        SOURCE_PATH="${FLAKE_DIR}/${src}"

        if [ "$type" == "file" ]; then
            ln -f "$SOURCE_PATH" "$TARGET_PATH"
        else
            ln -sfn "$src" "$TARGET_PATH"
        fi
        $GIT add -f -N "$TARGET_PATH" 2>/dev/null
    done
}

# 2. 인자 분석
DO_CLEAN=false
CLEAN_TARGET="user"
HOST_ID=""
SCOPE="home"
ACTION="switch"
INPUT_LOCK=""

for arg in "$@"; do
    case $arg in
        clean) DO_CLEAN=true ;;
        all) CLEAN_TARGET="all" ;;
        os|home) SCOPE="$arg" ;;
        switch|boot|test|update) ACTION="$arg" ;;
        *.lock) INPUT_LOCK="$arg" ;;
        *) HOST_ID="$arg" ;;
    esac
done

# 2-1. Clean 로직 처리
if [ "$DO_CLEAN" = true ]; then
    if [ "$CLEAN_TARGET" = "all" ]; then
        echo "🧹 [nh] Cleaning GC roots (Target: all, Keep: 3) with sudo..."
        sudo nh clean all --keep 3
    else
        echo "🧹 [nh] Cleaning GC roots (Target: $CLEAN_TARGET, Keep: 3)..."
        nh clean "$CLEAN_TARGET" --keep 3
    fi
    exit 0
fi

# 3. Host ID 로직
INFO_JSON="$NIXOS_PATH/dev/_info.json"
[ -z "$HOST_ID" ] && [ -f "$ID_FILE" ] && HOST_ID=$(cat "$ID_FILE")

if [ -z "$HOST_ID" ]; then
    echo "❌ Error: Host ID가 필요합니다."
    exit 1
fi

HOST_CONFIG=$(jq -e ".hosts[] | select(.hostname == \"$HOST_ID\")" "$INFO_JSON" 2>/dev/null)
if [ $? -ne 0 ]; then
    echo "❌ Error: '$HOST_ID'는 등록되지 않은 호스트입니다."
    exit 1
fi
echo "$HOST_ID" > "$ID_FILE"
IS_ROLLING=$(echo "$HOST_CONFIG" | jq -r '.isRolling')

# 4. Lock 파일 결정 및 업데이트 로직
SELECTED_LOCK=""

# 기본 Stable Lock 선택 (업데이트 베이스)
STABLE_LOCK="$STABLE_LOCKS_DIR/$HOST_ID.lock"
[ ! -f "$STABLE_LOCK" ] && STABLE_LOCK="$STABLE_LOCKS_DIR/_default.lock"

# 4-1. 입력된 락 파일 경로 지능적 해석
if [ -n "$INPUT_LOCK" ]; then
    RESOLVED_LOCK=""
    # 1) 입력된 경로 그대로 존재하는지 확인
    if [ -f "$INPUT_LOCK" ]; then
        RESOLVED_LOCK=$(readlink -f "$INPUT_LOCK")
    # 2) .locks/ 내에 존재하는지 확인
    elif [ -f "$STABLE_LOCKS_DIR/$INPUT_LOCK" ]; then
        RESOLVED_LOCK="$STABLE_LOCKS_DIR/$INPUT_LOCK"
    # 3) .locks/rolling/ 내에 존재하는지 확인
    elif [ -f "$LOCKS_DIR/$INPUT_LOCK" ]; then
        RESOLVED_LOCK="$LOCKS_DIR/$INPUT_LOCK"
    fi

    if [ -n "$RESOLVED_LOCK" ]; then
        echo "$RESOLVED_LOCK" > "$LOCK_FILE_PTR"
        echo "🎯 Pinning lock to: $RESOLVED_LOCK"
    else
        echo "❌ Error: Could not find lock file '$INPUT_LOCK'"
        exit 1
    fi
fi

# 4-2. 전용 Update 액션 처리
if [ "$ACTION" == "update" ]; then
    if [ -f "$TARGET_LOCK" ]; then
        echo "❌ Error: Another nhw.sh might be running."
        exit 1
    fi
    trap cleanup EXIT
    setup_links

    echo "🔄 Updating stable lock for $HOST_ID..."
    cp "$STABLE_LOCK" "$TARGET_LOCK"
    # 락 파일을 Git 추적에서 잠시 제외한 상태에서 업데이트 수행 (자동 커밋 방지)
    $GIT rm --cached "$TARGET_LOCK" > /dev/null 2>&1
    
    nix flake update --flake "$FLAKE_DIR"
    
    cp "$TARGET_LOCK" "$STABLE_LOCK"
    echo "✅ Update complete."
    exit 0
fi

# 5. 빌드 환경 구성
if [ -f "$TARGET_LOCK" ]; then
    echo "❌ Error: Another nhw.sh might be running."
    exit 1
fi
trap cleanup EXIT
setup_links

if [ -f "$LOCK_FILE_PTR" ]; then
    SELECTED_LOCK=$(cat "$LOCK_FILE_PTR")
    if [ ! -f "$SELECTED_LOCK" ]; then
        echo "❌ Error: Pinned lock file not found: $SELECTED_LOCK"
        rm -f "$LOCK_FILE_PTR"
        exit 1
    fi
    echo "⚠️  Using PINNED lock: $(basename $SELECTED_LOCK)"
elif [ "$IS_ROLLING" == "true" ]; then
    TIMESTAMP=$(date +%Y%m%dT%H%M%S)
    NEW_LOCK="$LOCKS_DIR/$TIMESTAMP.lock"
    echo "🌀 Rolling: Updating unstable..."
    mkdir -p "$LOCKS_DIR"
    cp "$STABLE_LOCK" "$TARGET_LOCK"
    
    # Git 인식 없이 업데이트를 먼저 하고 나중에 하드링크/교체하는 방식으로 전환
    # (nix flake update는 파일이 있어도 작동하며, Git 저장소 인식을 피하기 위해 --flake 경로만 명시)
    nix flake update --flake "$FLAKE_DIR" nixpkgs-unstable
    
    cp "$TARGET_LOCK" "$NEW_LOCK"
    SELECTED_LOCK="$NEW_LOCK"
    echo "📦 New lock: $(basename $SELECTED_LOCK)"
else
    SELECTED_LOCK="$STABLE_LOCK"
    echo "⚓ Using stable lock"
fi

if [ -f "$SELECTED_LOCK" ]; then
    ln -f "$SELECTED_LOCK" "$TARGET_LOCK"
    $GIT add -f -N "$TARGET_LOCK" 2>/dev/null
else
    echo "❌ Error: Lock not found: $SELECTED_LOCK"
    exit 1
fi

# 6. 빌드 실행
echo "🚀 [nh] Building #$HOST_ID with action $ACTION"
if [ "$SCOPE" == "os" ]; then
    nh os "$ACTION" "$FLAKE_DIR" -H "$HOST_ID"
else
    nh home "$ACTION" "$FLAKE_DIR"
fi
