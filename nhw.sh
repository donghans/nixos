#!/usr/bin/env nix-shell
#!nix-shell -i bash -p nh jq

# 1. 경로 설정 및 상수
NIXOS_PATH=$(dirname $(readlink -f "$0"))
GIT="git -C $NIXOS_PATH"

ENV_FILE="$NIXOS_PATH/.env"
FLAKE_DIR="$NIXOS_PATH/_flakes"
TARGET_LOCK="$FLAKE_DIR/flake.lock"

# .env 파일 업데이트 함수 (다른 변수 보존)
update_env() {
    local key=$1
    local value=$2
    if [ ! -f "$ENV_FILE" ]; then
        echo "$key=$value" > "$ENV_FILE"
    elif grep -q "^$key=" "$ENV_FILE"; then
        sed -i "s|^$key=.*|$key=$value|" "$ENV_FILE"
    else
        echo "$key=$value" >> "$ENV_FILE"
    fi
}

# .env 로드
if [ -f "$ENV_FILE" ]; then
    set -a; source "$ENV_FILE"; set +a
fi

LOCKS_DIR="$NIXOS_PATH/.locks/rolling"
STABLE_LOCKS_DIR="$NIXOS_PATH/.locks"
NH_TARGET="$FLAKE_DIR"

ITEMS=(
    "dev:../dev:dir"
    "lib:../lib:dir"
    ".env:../.env:file"
)

cleanup() {
    echo "🧹 Cleaning up temporary links and lock..."
    for item in "${ITEMS[@]}"; do
        IFS=':' read -r name src type <<< "$item"
        TARGET_PATH="${FLAKE_DIR}/${name}"
        [ -e "$TARGET_PATH" ] || [ -L "$TARGET_PATH" ] && rm -rf "$TARGET_PATH" && $GIT rm --cached "$TARGET_PATH" > /dev/null 2>&1
    done
    [ -f "$TARGET_LOCK" ] && rm -f "$TARGET_LOCK" && $GIT rm --cached "$TARGET_LOCK" > /dev/null 2>&1
}

setup_links() {
    echo "🔗 Preparing build environment (linking dev/lib)..."
    for item in "${ITEMS[@]}"; do
        IFS=':' read -r name src type <<< "$item"
        TARGET_PATH="${FLAKE_DIR}/${name}"
        if [ "$type" == "file" ]; then
            ln -f "${NIXOS_PATH}/${src#../}" "$TARGET_PATH"
        else
            ln -sfn "$src" "$TARGET_PATH"
        fi
        $GIT add -f -N "$TARGET_PATH" 2>/dev/null
    done
}

# 2. 인자 분석
DO_CLEAN=false; CLEAN_TARGET="user"; HOST_ID=""; SCOPE="home"; ACTION="switch"; INPUT_LOCK=""
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

if [ "$DO_CLEAN" = true ]; then
    [ "$CLEAN_TARGET" = "all" ] && sudo nh clean all --keep 3 || nh clean "$CLEAN_TARGET" --keep 3
    exit 0
fi

# 3. Host ID 로직
[ -z "$HOST_ID" ] && HOST_ID="$HOST"
[ -z "$HOST_ID" ] && echo "❌ Error: Host ID가 필요합니다." && exit 1

if [ "$HOST_ID" = "default" ] || [ "$HOST_ID" = "_default" ]; then
    HOST_ID="_default"
    IS_ROLLING="false"
    echo "🎯 Using special host: _default (Common lock for ISO/Templates)"
else
    INFO_JSON="$NIXOS_PATH/dev/_info.json"
    HOST_CONFIG=$(jq -e ".hosts[] | select(.hostname == \"$HOST_ID\")" "$INFO_JSON" 2>/dev/null)
    [ $? -ne 0 ] && echo "❌ Error: '$HOST_ID'는 등록되지 않은 호스트입니다." && exit 1
    update_env "HOST" "$HOST_ID"
    IS_ROLLING=$(echo "$HOST_CONFIG" | jq -r '.isRolling')
fi

# 4. Lock 파일 결정
SELECTED_LOCK=""
HOST_SPECIFIC_LOCK="$STABLE_LOCKS_DIR/$HOST_ID.lock"
STABLE_LOCK="$HOST_SPECIFIC_LOCK"
[ ! -f "$STABLE_LOCK" ] && STABLE_LOCK="$STABLE_LOCKS_DIR/_default.lock"

# 인자로 .lock 파일이 들어온 경우 (파일명만 추출하여 rolling/ 내에서 찾음)
if [ -n "$INPUT_LOCK" ]; then
    LOCK_NAME=$(basename "$INPUT_LOCK")
    if [ -f "$LOCKS_DIR/$LOCK_NAME" ]; then
        update_env "PINNED_LOCK" "$LOCK_NAME"
        echo "🎯 Pinning lock to rolling/$LOCK_NAME"
        PINNED_LOCK="$LOCK_NAME"
    else
        echo "❌ Error: Lock '$LOCK_NAME' not found in rolling/"; exit 1
    fi
fi

# 4-2. Update 액션
if [ "$ACTION" == "update" ]; then
    trap cleanup EXIT; setup_links
    echo "🔄 Updating stable lock for $HOST_ID..."
    cp "$STABLE_LOCK" "$TARGET_LOCK"
    $GIT add -f -N "$TARGET_LOCK" 2>/dev/null
    nix flake update --flake "$FLAKE_DIR"
    
    # 업데이트된 내용을 호스트 전용 락 파일로 저장 (없으면 생성됨)
    cp "$TARGET_LOCK" "$HOST_SPECIFIC_LOCK"
    echo "✅ Update complete. Saved to $HOST_SPECIFIC_LOCK"; exit 0
fi

# 5. 빌드 환경 구성
trap cleanup EXIT; setup_links

# PINNED_LOCK 이 설정되어 있으면 rolling/ 폴더에서 해당 파일 사용
if [ -n "$PINNED_LOCK" ]; then
    SELECTED_LOCK="$LOCKS_DIR/$PINNED_LOCK"
    if [ ! -f "$SELECTED_LOCK" ]; then
        echo "❌ Warning: Pinned lock rolling/$PINNED_LOCK not found. Falling back."
        update_env "PINNED_LOCK" ""
        SELECTED_LOCK=""
    else
        echo "⚠️  Using PINNED lock: $PINNED_LOCK"
    fi
fi

if [ -z "$SELECTED_LOCK" ]; then
    if [ "$IS_ROLLING" == "true" ]; then
        TIMESTAMP=$(date +%Y%m%dT%H%M%S)
        NEW_LOCK="$LOCKS_DIR/$TIMESTAMP.lock"
        echo "🌀 Rolling: Updating unstable only..."
        mkdir -p "$LOCKS_DIR"
        cp "$STABLE_LOCK" "$TARGET_LOCK"
        $GIT add -f -N "$TARGET_LOCK" 2>/dev/null
        nix flake update --flake "$FLAKE_DIR" nixpkgs-unstable
        cp "$TARGET_LOCK" "$NEW_LOCK"
        SELECTED_LOCK="$NEW_LOCK"
    else
        SELECTED_LOCK="$STABLE_LOCK"
        echo "⚓ Using stable lock"
    fi
fi

if [ -f "$SELECTED_LOCK" ]; then
    ln -f "$SELECTED_LOCK" "$TARGET_LOCK"
    $GIT add -f -N "$TARGET_LOCK" 2>/dev/null
else
    echo "❌ Error: Lock not found."; exit 1
fi

# 6. 빌드 실행
echo "🚀 [nh] Building #$HOST_ID with action $ACTION"
[ "$SCOPE" == "os" ] && nh os "$ACTION" "$FLAKE_DIR" -H "$HOST_ID" || nh home "$ACTION" "$FLAKE_DIR"
