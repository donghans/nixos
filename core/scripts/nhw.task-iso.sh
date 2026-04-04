#!/usr/bin/env bash

run_iso_task() {
    log_msg "Task" "starting ISO image build process..."
    cd "$TMP_BUILD_DIR" || exit 1
    
    log_exec "nom" ">"
    nom build ".#nixosConfigurations.custom-iso.config.system.build.isoImage" \
      --extra-experimental-features "nix-command flakes" --impure --print-build-logs
    log_exec "nom" "<"

    if [ -L "$TMP_BUILD_DIR/result" ]; then
        ISO_FILE=$(readlink -f "$TMP_BUILD_DIR/result/iso/"*.iso)
        ISO_NAME=$(basename "$ISO_FILE")
        cp "$ISO_FILE" "$TMP_BUILD_DIR/"
        rm -f "$TMP_BUILD_DIR/result"
        log_msg "Done" "ISO successfully created: .build/$ISO_NAME"
    else
        log_msg "Error" "ISO build failed."
        exit 1
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "redirecting to nhw dispatcher..."
    exec nhw iso
fi

run_iso_task
