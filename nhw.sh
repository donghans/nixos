#!/usr/bin/env nix-shell
#!nix-shell -i bash -p nh

# 1. 경로 설정 및 상수
NIXOS_PATH=$(dirname $(readlink -f "$0"))
GIT="git -C $NIXOS_PATH"

DO_CLEAN=false
CLEAN_TARGET="user"

ID_FILE="$NIXOS_PATH/.current_host"
HOST_ID=""

SCOPE="home"
ACTION="switch"
FLAKE="stable" # 기본 Flake

# 2. 인자 분석 (예: ./manage.sh laptop switch rolling)
for arg in "$@"; do
    case $arg in
        clean) DO_CLEAN=true ;;
        all) CLEAN_TARGET="all" ;;

        os|home) SCOPE="$arg" ;;
        switch|boot|test|update) ACTION="$arg" ;;
        rolling|stable) FLAKE="$arg" ;;
        *) HOST_ID="$arg" ;;
    esac
done

# 2-1. Clean 로직 처리 (다른 로직 무시하고 즉시 실행 후 종료)
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
if [ -z "$HOST_ID" ]; then
    if [ -f "$ID_FILE" ]; then
        HOST_ID=$(cat "$ID_FILE")
    else
        echo "❌ Error: Host ID를 입력하거나 .current_host 파일이 필요합니다."
        exit 1
    fi
else
    # Host ID 유효성 검사 (_info.json 기준)
    INFO_JSON="$NIXOS_PATH/dev/_info.json"
    if [ -f "$INFO_JSON" ]; then
        # jq를 사용하여 hosts 배열 내에 해당 hostname이 있는지 확인
        if ! jq -e ".hosts[] | select(.hostname == \"$HOST_ID\")" "$INFO_JSON" > /dev/null; then
            echo "❌ Error: '$HOST_ID'는 dev/_info.json의 호스트 목록에 존재하지 않습니다."
            echo "📍 등록된 호스트: $(jq -r '.hosts[].hostname' "$INFO_JSON" | tr '\n' ' ')"
            exit 1
        fi
    fi
    echo "$HOST_ID" > "$ID_FILE"
fi

# 4. 브랜치 전략
CURRENT_BRANCH=$($GIT branch --show-current)
if [ "$FLAKE" == "rolling" ]; then
    echo "🌿 Switching to local update branch [rolling]..."
    $GIT checkout rolling 2>/dev/null || git checkout -b rolling

    # 메인 설정 반영 (자동 머지)
    echo "🔄 Merging stable into rolling to keep logic sync..."
    $GIT merge stable --no-edit
fi

# 5. 빌드 실행 (nh 사용)
echo "🚀 [nh] Building NixOS ($FLAKE) for #$HOST_ID with scope $SCOPE and action $ACTION"
# 실제 빌드 경로는 Flake 디렉터리를 가리킵니다.
if [ "$SCOPE" == "os" ]; then
    nh os "$ACTION" "$NIXOS_PATH/_flakes/$FLAKE" -H "$HOST_ID"
elif [ "$SCOPE" == "home" ]; then
    nh home "$ACTION" "$NIXOS_PATH/_flakes/$FLAKE"
else
    echo "X Error: 명령어가 등록되지 않은 스코프입니다: $SCOPE, nhw.sh 스크립트에 추가해주세요!"
fi

# 6. 빌드 후 메인 브랜치로 복귀 (선택 사항)
if [ "$FLAKE" == "rolling" ]; then
    $GIT checkout "$CURRENT_BRANCH"
fi
