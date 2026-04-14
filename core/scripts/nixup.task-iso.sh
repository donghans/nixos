#!/usr/bin/env bash

run_iso_task() {
    local iso_target="custom-iso"
    if [ "${ISO_ARCH:-x86_64}" = "aarch64" ]; then
        iso_target="custom-iso-aarch64"
    fi

    # (목적: GC 루트를 tmpfs(/tmp)에 두어 재부팅 후 자동 소멸.
    #         ISO 실체는 nix store에 유지되며 GC 루트 소멸 후 nixup clean 시 함께 정리됨.
    #         .build/에는 nix store 경로로의 심볼릭링크만 생성 — 파일 복사 없음.)
    local gc_root_dir="/tmp/nixup-iso"
    local gc_root="$gc_root_dir/result"
    local build_log="$LOG_DIR/${LOG_TIMESTAMP}.nom-build.log"

    log_msg "Task" "starting ISO image build process... [${ISO_ARCH:-x86_64}]"

    mkdir -p "$gc_root_dir"
    log_exec "nix" ">" "nix build iso (nom)"
    set +e
    nix build "path:$BUILD_DIR#nixosConfigurations.${iso_target}.config.system.build.isoImage" \
        "${NIX_FLAKE_FLAGS[@]}" --impure \
        --log-format internal-json \
        --print-build-logs \
        --out-link "$gc_root" \
        2>&1 | tee "$build_log" | nom --json >&3 2>&3
    BUILD_EXIT=${PIPESTATUS[0]}
    set -e
    log_exec "nix" "<" "nix build iso (nom)"

    if [ "$BUILD_EXIT" -ne 0 ]; then
        log_msg "Error" "ISO build failed. Build log: $build_log"
        exit 1
    fi

    rm -f "$build_log"

    if [ -L "$gc_root" ]; then
        ISO_FILE=$(find "$gc_root/iso/" -maxdepth 1 -name '*.iso' -print -quit)
        ISO_FILE=$(readlink -f "$ISO_FILE")
        ISO_NAME=$(basename "$ISO_FILE")

        ln -sf "$ISO_FILE" "$BUILD_DIR/$ISO_NAME"
        log_msg "Done" "ISO successfully created: $ISO_NAME"
        log_msg "Done" "Store path: $ISO_FILE"
        log_msg "Done" "Symlink: $NIXOS_PATH/.build/$ISO_NAME"
    else
        log_msg "Error" "ISO build failed: result link not found."
        exit 1
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "redirecting to nixup dispatcher..."
    exec nixup iso
fi

run_iso_task
