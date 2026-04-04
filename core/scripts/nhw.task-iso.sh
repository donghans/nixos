#!/usr/bin/env bash

# 태스크 로직 함수
run_iso_task() {
    echo "[nhw:task] Building ISO Image..."
    cd "$TMP_BUILD_DIR" || exit 1
    nom build ".#nixosConfigurations.custom-iso.config.system.build.isoImage" \
      --extra-experimental-features "nix-command flakes" --impure --print-build-logs

    if [ -L "$TMP_BUILD_DIR/result" ]; then
        ISO_FILE=$(readlink -f "$TMP_BUILD_DIR/result/iso/"*.iso)
        ISO_NAME=$(basename "$ISO_FILE")
        cp "$ISO_FILE" "$TMP_BUILD_DIR/"
        rm -f "$TMP_BUILD_DIR/result"
        echo -e "\n[nhw] ISO Build Success: .build/$ISO_NAME"
    else
        echo "[nhw:error] ISO Build Failed"; exit 1
    fi
}

# 직접 실행 시 nhw 환경으로 리다이렉트
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "[nhw:notice] Redirecting to nhw dispatcher..."
    # 이 스크립트는 이제 시스템 패키지로 등록될 것이므로 'nhw' 명령어를 직접 호출 가능
    exec nhw iso
fi

# nhw.sh에 의해 source된 경우 실행
run_iso_task
