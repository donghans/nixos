#!/usr/bin/env nix-shell
#!nix-shell -i bash -p curl jq git nix-prefetch

# 1. 인자 분석
PKG_NAME=""
DRY_RUN=false

for arg in "$@"; do
    case $arg in
        --dry-run) DRY_RUN=true ;;
        *) [ -z "$PKG_NAME" ] && PKG_NAME="$arg" ;;
    esac
done

if [ -z "$PKG_NAME" ]; then
    echo "❌ Usage: $0 [package-name] [--dry-run]"
    exit 1
fi

ENV_FILE="$(dirname $(readlink -f "$0"))/../.env"
REPO="NixOS/nixpkgs"

[ "$DRY_RUN" = false ] && echo "🔍 Searching for the last stable commit of '$PKG_NAME'..." >&2

# 2. 패키지 경로 찾기
SEARCH_PATH=$(curl -s "https://api.github.com/search/code?q=filename:package.nix+path:pkgs/by-name/**/${PKG_NAME}+repo:${REPO}" | jq -r '.items[0].path')
if [ "$SEARCH_PATH" == "null" ] || [ -z "$SEARCH_PATH" ]; then
    SEARCH_PATH=$(curl -s "https://api.github.com/search/code?q=filename:default.nix+${PKG_NAME}+path:pkgs/**+repo:${REPO}" | jq -r '.items[0].path')
fi

if [ "$SEARCH_PATH" == "null" ] || [ -z "$SEARCH_PATH" ]; then
    echo "❌ Could not find package path." >&2
    exit 1
fi

# 3. 커밋 히스토리 조회
COMMITS=$(curl -s "https://api.github.com/repos/${REPO}/commits?path=${SEARCH_PATH}")
GOOD_COMMIT=$(echo "$COMMITS" | jq -r '.[1].sha') 
COMMIT_DATE=$(echo "$COMMITS" | jq -r '.[1].commit.committer.date')
TIMESTAMP=$(date -d "$COMMIT_DATE" +%s)

if [ -z "$GOOD_COMMIT" ] || [ "$GOOD_COMMIT" == "null" ]; then
    echo "❌ Could not find a suitable previous commit." >&2
    exit 1
fi

# 4. SRI Hash 계산
TARBALL_URL="https://github.com/${REPO}/archive/${GOOD_COMMIT}.tar.gz"
SHA256=$(nix-prefetch-url --unpack "$TARBALL_URL" 2>/dev/null)
SRI_HASH=$(nix hash to-sri --type sha256 "$SHA256")

# 5. 결과 출력
if [ "$DRY_RUN" = true ]; then
    echo "REV:$GOOD_COMMIT"
    echo "SHA:$SRI_HASH"
    echo "DATE:$TIMESTAMP"
    exit 0
fi

echo "✨ Result:"
echo "   REV: $GOOD_COMMIT"
echo "   SHA: $SRI_HASH"
echo "   DATE: $COMMIT_DATE ($TIMESTAMP)"

# 6. .env 업데이트
update_env() {
    local key=$1
    local value=$2
    if grep -q "^$key=" "$ENV_FILE"; then
        sed -i "s|^$key=.*|$key=$value|" "$ENV_FILE"
    else
        echo "$key=$value" >> "$ENV_FILE"
    fi
}

if [ -f "$ENV_FILE" ]; then
    update_env "UNSTABLE_FALLBACK_REV" "$GOOD_COMMIT"
    update_env "UNSTABLE_FALLBACK_SHA" "$SRI_HASH"
    echo "🚀 Updated $ENV_FILE successfully."
else
    echo "UNSTABLE_FALLBACK_REV=$GOOD_COMMIT" > "$ENV_FILE"
    echo "UNSTABLE_FALLBACK_SHA=$SRI_HASH" >> "$ENV_FILE"
    echo "📝 Created new $ENV_FILE."
fi
