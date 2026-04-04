#!/usr/bin/env bash

run_iso_task() {
    log_msg "Task" "starting ISO image build process..."
    cd "$TMP_BUILD_DIR" || exit 1
    
    log_exec "nom" ">" "nom build iso"
    if nom build ".#nixosConfigurations.custom-iso.config.system.build.isoImage" \
      --extra-experimental-features "nix-command flakes" --impure --print-build-logs; then
        log_exec "nom" "<" "nom build iso"

        if [ -L "$TMP_BUILD_DIR/result" ]; then
            ISO_FILE=$(readlink -f "$TMP_BUILD_DIR/result/iso/"*.iso)
            ISO_NAME=$(basename "$ISO_FILE")
            
            # Create persistent .iso directory in project root
            mkdir -p "$NIXOS_PATH/.iso"
            
            # Copy to both temp (for .build/ reference) and persistent .iso/
            cp "$ISO_FILE" "$TMP_BUILD_DIR/"
            cp "$ISO_FILE" "$NIXOS_PATH/.iso/"
            
            rm -f "$TMP_BUILD_DIR/result"
            log_msg "Done" "ISO successfully created: .iso/$ISO_NAME"
            log_msg "Done" "You can find it in: $NIXOS_PATH/.iso/$ISO_NAME"
        else
            log_msg "Error" "ISO build failed: result link not found."
            exit 1
        fi
    else
        log_exec "nom" "<" "nom build iso"
        log_msg "Error" "ISO build failed."
        exit 1
    fi
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "redirecting to nhw dispatcher..."
    exec nhw iso
fi

run_iso_task
