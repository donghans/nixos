#!/usr/bin/env nix-shell
#!nix-shell -i bash -p nix-output-monitor git

# 1. 경로 설정
ROOT_PATH=$(dirname $(readlink -f "$0"))
TARGET_DIR="${ROOT_PATH}/_iso"

# [중요] 이전 빌드 결과물 제거 (성공 여부 오판 방지)
rm -f "${ROOT_PATH}/result"

# 연결할 항목 정의 (이름:원본상대경로:타입)
ITEMS=(
    "flake.nix:../_flakes/stable/flake.nix:file"
    "flake.lock:../_flakes/stable/flake.lock:file"
    "_info.json:../dev/_info.json:file"
    "lib:../lib:dir"
)

# 2. Cleanup 함수
cleanup() {
    echo ""
    echo "🧹 빌드 환경 정리 중..."
    for item in "${ITEMS[@]}"; do
        IFS=':' read -r name src type <<< "$item"
        TARGET_PATH="${TARGET_DIR}/${name}"

        if [ -e "$TARGET_PATH" ] || [ -L "$TARGET_PATH" ]; then
            echo "  - 제거: $name"
            rm -rf "$TARGET_PATH"
            git -C "$ROOT_PATH" rm --cached "$TARGET_PATH" > /dev/null 2>&1
        fi
    done
}

trap cleanup EXIT

# 3. 링크 생성
echo "🔗 빌드용 임시 환경 구성 중 (하드 링크 활용)..."
mkdir -p "$TARGET_DIR"

for item in "${ITEMS[@]}"; do
    IFS=':' read -r name src type <<< "$item"
    TARGET_PATH="${TARGET_DIR}/${name}"
    SOURCE_PATH="${TARGET_DIR}/${src}"

    if [ "$type" == "file" ]; then
        # 파일은 하드 링크로 생성 (원본과 동일하게 취급됨)
        ln "$SOURCE_PATH" "$TARGET_PATH"
        echo "  - 하드 링크 생성: $name"
    else
        # 디렉터리는 어쩔 수 없이 심볼릭 링크 사용
        ln -sfn "$src" "$TARGET_PATH"
        echo "  - 심볼릭 링크 생성: $name"
    fi

    # Nix 인지용 Git 추가
    git -C "$ROOT_PATH" add -f -N "$TARGET_PATH" 2>/dev/null
done

# 4. 빌드 실행
echo "🚀 커스텀 ISO 빌드 시작"

nom build "git+file://${ROOT_PATH}?dir=iso#nixosConfigurations.custom-iso.config.system.build.isoImage" \
  --extra-experimental-features "nix-command flakes" \
  --impure \
  --print-build-logs

# 5. 결과 확인 (현재 디렉터리의 result 링크 존재 여부 확인)
if [ -L "${ROOT_PATH}/result" ]; then
  ISO_FILE=$(readlink -f "${ROOT_PATH}/result/iso/*.iso")
  echo "--------------------------------------------------"
  echo "✅ 빌드 성공!"
  echo "📍 ISO 위치: $ISO_FILE"
  echo "--------------------------------------------------"
else
  echo "--------------------------------------------------"
  echo "❌ 빌드 실패: 로그를 확인해 주세요."
  echo "--------------------------------------------------"
  exit 1
fi
