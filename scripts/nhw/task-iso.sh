#!/usr/bin/env bash

# 태스크 로직 함수
run_iso_task() {
    echo "🚀 [nom] Building ISO Image"
    cd "$TMP_BUILD_DIR" || exit 1
    nom build ".#nixosConfigurations.custom-iso.config.system.build.isoImage" \
      --extra-experimental-features "nix-command flakes" --impure --print-build-logs

    if [ -L "$TMP_BUILD_DIR/result" ]; then
        ISO_FILE=$(readlink -f "$TMP_BUILD_DIR/result/iso/"*.iso)
        ISO_NAME=$(basename "$ISO_FILE")
        cp "$ISO_FILE" "$TMP_BUILD_DIR/"
        rm -f "$TMP_BUILD_DIR/result"
        echo -e "\n✅ ISO Build Success: .build/$ISO_NAME"
    else
        echo "❌ ISO Build Failed"; exit 1
    fi
}

# 직접 실행 시 nhw.sh로 리다이렉트
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "⚠️  직접 실행 감지: nhw.sh 환경으로 전환합니다..."
    exec "$(dirname "$0")/../../nhw.sh" iso
fi

# nhw.sh에 의해 source된 경우 실행
run_iso_task
