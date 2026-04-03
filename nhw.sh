#!/usr/bin/env nix-shell
#!nix-shell -i bash -p nh jq

# 1. 경로 설정 및 상수
NIXOS_PATH=$(dirname $(readlink -f "$0"))
GIT="git -C $NIXOS_PATH"

ID_FILE="$NIXOS_PATH/.current_host"
LOCK_FILE_PTR="$NIXOS_PATH/.current_lock"
FLAKE_DIR="$NIXOS_PATH/_flakes"
TARGET_LOCK="$FLAKE_DIR/flake.lock"

# 중복 실행 방지 및 Cleanup 설정
cleanup() {
    if [ -f "$TARGET_LOCK" ]; then
        echo "🧹 Cleaning up temporary flake.lock..."
        rm -f "$TARGET_LOCK"
        $GIT rm --cached "$TARGET_LOCK" > /dev/null 2>&1
    fi
}

# 2. 인자 분석
DO_CLEAN=false
CLEAN_TARGET="user"
HOST_ID=""
SCOPE="home"
ACTION="switch"
MANUAL_LOCK=""

for arg in "$@"; do
    case $arg in
        clean) DO_CLEAN=true ;;
        all) CLEAN_TARGET="all" ;;
        os|home) SCOPE="$arg" ;;
        switch|boot|test|update) ACTION="$arg" ;;
        *.lock) MANUAL_LOCK="$arg" ;;
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
    echo "❌ Error: Host ID를 입력하거나 .current_host 파일이 필요합니다."
    exit 1
fi

HOST_CONFIG=$(jq -e ".hosts[] | select(.hostname == \"$HOST_ID\")" "$INFO_JSON" 2>/dev/null)
if [ $? -ne 0 ]; then
    echo "❌ Error: '$HOST_ID'는 dev/_info.json의 호스트 목록에 존재하지 않습니다."
    echo "📍 등록된 호스트: $(jq -r '.hosts[].hostname' "$INFO_JSON" | tr '\n' ' ')"
    exit 1
fi
echo "$HOST_ID" > "$ID_FILE"
IS_ROLLING=$(echo "$HOST_CONFIG" | jq -r '.isRolling')

# 4. Lock 파일 결정 및 업데이트 로직
SELECTED_LOCK=""
LOCKS_DIR="$FLAKE_DIR/locks.rolling"
STABLE_LOCKS_DIR="$FLAKE_DIR/locks.stable"

# 기본 Stable Lock 선택 (업데이트 베이스)
STABLE_LOCK="$STABLE_LOCKS_DIR/$HOST_ID.lock"
[ ! -f "$STABLE_LOCK" ] && STABLE_LOCK="$STABLE_LOCKS_DIR/default.lock"

# MANUAL_LOCK이 제공되면 .current_lock 갱신
if [ -n "$MANUAL_LOCK" ]; then
    echo "$MANUAL_LOCK" > "$LOCK_FILE_PTR"
    echo "📝 Updated .current_lock with manual input: $MANUAL_LOCK"
fi

# 4-1. 전용 Update 액션 처리 (정석적 동작: 업데이트만 수행 후 종료)
if [ "$ACTION" == "update" ]; then
    if [ -f "$TARGET_LOCK" ]; then
        echo "❌ Error: $TARGET_LOCK already exists. Cannot update right now."
        exit 1
    fi

    echo "🔄 Updating stable lock for $HOST_ID..."
    cp "$STABLE_LOCK" "$TARGET_LOCK"
    nix flake update --flake "$FLAKE_DIR" --commit-lock-file false
    cp "$TARGET_LOCK" "$STABLE_LOCK"
    rm -f "$TARGET_LOCK"
    
    echo "✅ Update complete. Use 'switch' to apply changes."
    exit 0
fi

# 5. 빌드 환경 구성 (switch, boot, test 등)
if [ -f "$TARGET_LOCK" ]; then
    echo "❌ Error: $TARGET_LOCK already exists. Another nhw.sh might be running."
    exit 1
fi
trap cleanup EXIT

# 락 선택 우선순위 및 경고
if [ -f "$LOCK_FILE_PTR" ]; then
    SELECTED_LOCK=$(cat "$LOCK_FILE_PTR")
    echo "⚠️  WARNING: You are using a PINNED lock file!"
    echo "   📍 Path: $SELECTED_LOCK"
    echo "   (This ignores the default stable/rolling logic until .current_lock is removed.)"
elif [ "$IS_ROLLING" == "true" ]; then
    TIMESTAMP=$(date +%Y%m%dT%H%M%S)
    NEW_LOCK="$LOCKS_DIR/$TIMESTAMP.lock"
    echo "🌀 Rolling: Updating unstable channel..."
    mkdir -p "$LOCKS_DIR"
    cp "$STABLE_LOCK" "$TARGET_LOCK"
    nix flake update --flake "$FLAKE_DIR" nixpkgs-unstable --commit-lock-file false
    cp "$TARGET_LOCK" "$NEW_LOCK"
    SELECTED_LOCK="$NEW_LOCK"
    echo "📦 New rolling lock created: $(basename $SELECTED_LOCK)"
else
    SELECTED_LOCK="$STABLE_LOCK"
    echo "⚓ Using stable lock"
fi

if [ -f "$SELECTED_LOCK" ]; then
    ln -f "$SELECTED_LOCK" "$TARGET_LOCK"
    $GIT add -f -N "$TARGET_LOCK" 2>/dev/null
else
    echo "❌ Error: Lock file not found: $SELECTED_LOCK"
    exit 1
fi

# 6. 빌드 실행 (nh 사용)
echo "🚀 [nh] Building NixOS for #$HOST_ID (Rolling: $IS_ROLLING) with action $ACTION"
if [ "$SCOPE" == "os" ]; then
    nh os "$ACTION" "$FLAKE_DIR" -H "$HOST_ID"
elif [ "$SCOPE" == "home" ]; then
    nh home "$ACTION" "$FLAKE_DIR"
else
    echo "❌ Error: Unknown scope: $SCOPE"
    exit 1
fi
