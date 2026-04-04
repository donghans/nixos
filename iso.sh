#!/usr/bin/env nix-shell
#!nix-shell -i bash -p nix-output-monitor git

# 1. 중복 실행 방지 락
exec 9> "/tmp/nixos-build.lock"
if ! flock -n 9; then
    echo "❌ Error: 다른 빌드 스크립트(nhw.sh 또는 iso.sh)가 이미 실행 중입니다."
    exit 1
fi

# 2. 경로 설정
ROOT_PATH=$(dirname $(readlink -f "$0"))
TMP_BUILD_DIR="/tmp/nixos-build"
STABLE_LOCKS_DIR="${ROOT_PATH}/.locks"
ROLLING_LOCK="${STABLE_LOCKS_DIR}/_rolling.lock"

# _rolling.lock 존재 여부 확인
if [ ! -f "$ROLLING_LOCK" ]; then
    echo "❌ Error: _rolling.lock이 존재하지 않습니다."
    echo "   './nhw.sh <host_id> update' 또는 rolling 호스트를 대상으로 ./nhw.sh를 실행하여 락 파일을 먼저 생성해 주세요."
    exit 1
fi

# 3. Cleanup 함수
cleanup() {
    echo ""
    echo "🧹 빌드 환경 정리 중..."
    # tmpfs 위에서 작업하므로 별도의 git index 정리가 불필요합니다.
}
trap cleanup EXIT

# 4. 빌드 환경 구성
echo "🔗 임시 빌드 환경 구성 중 ($TMP_BUILD_DIR)..."
rm -rf "$TMP_BUILD_DIR"
mkdir -p "$TMP_BUILD_DIR"

cp -a "$ROOT_PATH/core/"* "$TMP_BUILD_DIR/"
cp -a "$ROOT_PATH/dev" "$TMP_BUILD_DIR/"
cp -a "$ROOT_PATH/lib" "$TMP_BUILD_DIR/"
cp "$ROLLING_LOCK" "$TMP_BUILD_DIR/flake.lock"

# 사용자가 쉽게 접근할 수 있도록 .build 심볼릭 링크 갱신
ln -sfn "$TMP_BUILD_DIR" "$ROOT_PATH/.build"

# Git 레포지토리 초기화 (Nix Flake의 필수 요구사항 우회)
git -C "$TMP_BUILD_DIR" init >/dev/null 2>&1
git -C "$TMP_BUILD_DIR" add -A >/dev/null 2>&1

# 5. 빌드 실행
echo "🚀 커스텀 ISO 빌드 시작"
# 임시 빌드 폴더 내에서 실행하여 원본 프로젝트를 더럽히지 않음
cd "$TMP_BUILD_DIR" || exit 1
nom build ".#nixosConfigurations.custom-iso.config.system.build.isoImage" \
  --extra-experimental-features "nix-command flakes" \
  --impure \
  --print-build-logs

# 6. 결과 확인 및 처리
if [ -L "$TMP_BUILD_DIR/result" ]; then
  # Nix Store에 생성된 ISO 파일의 실제 경로 추적
  ISO_FILE=$(readlink -f "$TMP_BUILD_DIR/result/iso/"*.iso)
  ISO_NAME=$(basename "$ISO_FILE")
  
  echo "📦 ISO 파일 추출 중..."
  # result 심볼릭 링크 대신 실제 파일을 임시 폴더 최상단으로 복사
  cp "$ISO_FILE" "$TMP_BUILD_DIR/"
  rm -f "$TMP_BUILD_DIR/result"
  
  echo "--------------------------------------------------"
  echo "✅ 빌드 성공!"
  echo "📍 ISO 위치: $ROOT_PATH/.build/$ISO_NAME"
  echo "--------------------------------------------------"
else
  echo "--------------------------------------------------"
  echo "❌ 빌드 실패: 로그를 확인해 주세요."
  echo "--------------------------------------------------"
  exit 1
fi
