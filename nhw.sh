#!/usr/bin/env nix-shell
#!nix-shell -i bash -p nh jq

# 1. 중복 실행 방지 락
exec 9> "/tmp/nixos-build.lock"
if ! flock -n 9; then
    echo "❌ Error: 다른 빌드 스크립트(nhw.sh 또는 iso.sh)가 이미 실행 중입니다."
    exit 1
fi

# 2. 경로 설정 및 상수
NIXOS_PATH=$(dirname $(readlink -f "$0"))
ENV_FILE="$NIXOS_PATH/.env"
TMP_BUILD_DIR="/tmp/nixos-build"
TARGET_LOCK="$TMP_BUILD_DIR/flake.lock"

# .env 파일 업데이트 함수
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

cleanup() {
    echo "🧹 Cleaning up..."
    if [ "$LOCK_CHANGED" = true ]; then
        echo -e "\n📝 [Notice] Lock file has been updated: $HOST_SPECIFIC_LOCK"
        echo "   Please review and commit the changes."
    fi
}
trap cleanup EXIT

setup_env() {
    echo "🔗 Preparing isolated build environment in $TMP_BUILD_DIR..."
    rm -rf "$TMP_BUILD_DIR"
    mkdir -p "$TMP_BUILD_DIR"
    
    # core 디렉터리의 파일들(flake.nix 등)을 TMP_BUILD_DIR의 루트로 복사
    cp -a "$NIXOS_PATH/core/"* "$TMP_BUILD_DIR/"
    cp -a "$NIXOS_PATH/dev" "$TMP_BUILD_DIR/"
    cp -a "$NIXOS_PATH/lib" "$TMP_BUILD_DIR/"
    [ -f "$ENV_FILE" ] && cp -a "$ENV_FILE" "$TMP_BUILD_DIR/.env"
    
    # .build 심볼릭 링크 생성 (사용자가 볼 수 있도록)
    ln -sfn "$TMP_BUILD_DIR" "$NIXOS_PATH/.build"
}

# 3. 인자 분석
DO_CLEAN=false; CLEAN_TARGET="user"; HOST_ID=""; SCOPE="home"; ACTION="switch"; INPUT_LOCK=""; LOCK_CHANGED=false
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

# 4. Host ID 로직
[ -z "$HOST_ID" ] && HOST_ID="$HOST"
[ -z "$HOST_ID" ] && echo "❌ Error: Host ID가 필요합니다." && exit 1

if [ "$HOST_ID" = "default" ] || [ "$HOST_ID" = "_default" ]; then
    HOST_ID="_default"
    IS_ROLLING="false"
    echo "🎯 Using special host: _default (Common lock for Templates)"
else
    INFO_JSON="$NIXOS_PATH/dev/_info.json"
    HOST_CONFIG=$(jq -e ".hosts[] | select(.hostname == \"$HOST_ID\")" "$INFO_JSON" 2>/dev/null)
    [ $? -ne 0 ] && echo "❌ Error: '$HOST_ID'는 등록되지 않은 호스트입니다." && exit 1
    update_env "HOST" "$HOST_ID"
    IS_ROLLING=$(echo "$HOST_CONFIG" | jq -r '.isRolling')
fi

# 5. Lock 파일 결정
SELECTED_LOCK=""
if [ "$IS_ROLLING" == "true" ]; then
    HOST_SPECIFIC_LOCK="$STABLE_LOCKS_DIR/_rolling.lock"
else
    HOST_SPECIFIC_LOCK="$STABLE_LOCKS_DIR/$HOST_ID.lock"
fi
STABLE_LOCK="$HOST_SPECIFIC_LOCK"

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

# 6. 빌드 환경 구성
setup_env

# 6-1. Update 액션
if [ "$ACTION" == "update" ]; then
    echo "🔄 Updating lock for $HOST_ID..."
    
    [ -f "$STABLE_LOCK" ] && cp "$STABLE_LOCK" "$TARGET_LOCK"
    
    # Nix flake가 Git 저장소임을 인식하도록 초기화
    git -C "$TMP_BUILD_DIR" init >/dev/null 2>&1
    git -C "$TMP_BUILD_DIR" add -A >/dev/null 2>&1
    
    nix flake update --flake "$TMP_BUILD_DIR"
    
    if [ ! -f "$STABLE_LOCK" ] || ! cmp -s "$STABLE_LOCK" "$TARGET_LOCK"; then
        cp "$TARGET_LOCK" "$HOST_SPECIFIC_LOCK"
        LOCK_CHANGED=true
        echo "✅ Update complete. Saved to $HOST_SPECIFIC_LOCK"
    else
        echo "ℹ️ No changes in flake.lock"
    fi
    exit 0
fi

# PINNED_LOCK 이 설정되어 있으면 해당 파일 사용
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
        echo "🌀 Rolling: Updating unstable only..."
        [ -f "$STABLE_LOCK" ] && cp "$STABLE_LOCK" "$TARGET_LOCK"
        
        git -C "$TMP_BUILD_DIR" init >/dev/null 2>&1
        git -C "$TMP_BUILD_DIR" add -A >/dev/null 2>&1
        
        if [ -f "$TARGET_LOCK" ]; then
            nix flake update --flake "$TMP_BUILD_DIR" nixpkgs-unstable
        else
            nix flake update --flake "$TMP_BUILD_DIR"
        fi
        
        if [ ! -f "$STABLE_LOCK" ] || ! cmp -s "$STABLE_LOCK" "$TARGET_LOCK"; then
            cp "$TARGET_LOCK" "$HOST_SPECIFIC_LOCK"
            LOCK_CHANGED=true
            echo "✨ _rolling.lock updated"
        else
            echo "ℹ️ No changes in nixpkgs-unstable"
        fi
        SELECTED_LOCK="$HOST_SPECIFIC_LOCK"
    else
        SELECTED_LOCK="$STABLE_LOCK"
        echo "⚓ Using stable lock"
    fi
fi

if [ -f "$SELECTED_LOCK" ]; then
    cp "$SELECTED_LOCK" "$TARGET_LOCK"
else
    echo "❌ Error: Lock not found."; exit 1
fi

# 최종적으로 nh가 읽을 수 있도록 임시 레포지토리의 상태를 커밋
git -C "$TMP_BUILD_DIR" init >/dev/null 2>&1
git -C "$TMP_BUILD_DIR" add -A >/dev/null 2>&1

# 7. 빌드 실행
echo "🚀 [nh] Building #$HOST_ID with action $ACTION"
[ "$SCOPE" == "os" ] && nh os "$ACTION" "$TMP_BUILD_DIR" -H "$HOST_ID" || nh home "$ACTION" "$TMP_BUILD_DIR"
