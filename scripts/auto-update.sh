#!/usr/bin/env bash
# scripts/auto-update.sh

PROJECT_DIR="$HOME/nixos"
cd "$PROJECT_DIR"

# 1. 브랜치 전환 및 메인 병합
git checkout rolling
git merge stable -m "Routine: sync with stable before update"

# 2. Flake 업데이트 및 테스트 빌드
echo "🔄 Updating flake.lock..."
nix flake update

echo "🏗️ Testing build..."
# 실제로 스위치하지 않고 빌드만 시도해서 무결성 체크
if nix build .#laptop --no-link; then # TODO: .current_host 활용할 것
    echo "✅ Build successful. Committing changes."
    git add flake.lock
    git commit -m "Routine: auto-update flake.lock $(date +%Y-%m-%d)"
else
    echo "❌ Build failed! Rolling back flake.lock."
    git checkout flake.lock
    exit 1
fi

# 3. 원래 브랜치로 복귀
git checkout stable
