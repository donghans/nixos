#!/usr/bin/env bash
# core/scripts/nhw.task-check.sh
# Integrated task for project code integrity verification and anti-pattern cleanup

run_check_task() {
    # 1. Dead code check (deadnix)
    log_msg "Task" "Step 1: Searching for unused code (deadnix)"
    log_exec "nix" ">" "deadnix"
    nix-shell -p deadnix --run "deadnix $NIXOS_PATH"
    log_exec "nix" "<" "deadnix"

    # 2. Anti-pattern fix (statix fix)
    log_msg "Task" "Step 2: Auto-fixing anti-patterns (statix fix)"
    log_exec "nix" ">" "statix fix"
    nix-shell -p statix --run "statix fix $NIXOS_PATH"
    log_exec "nix" "<" "statix fix"

    # 3. Code Formatting (alejandra)
    log_msg "Task" "Step 3: Formatting code (alejandra)"
    log_exec "nix" ">" "alejandra"
    nix-shell -p alejandra --run "alejandra -q $NIXOS_PATH"
    log_exec "nix" "<" "alejandra"

    # 4. Exception Handling (flake.nix spacing)
    log_msg "Task" "Step 4: Special exception handling (flake.nix spacing)"
    # Restore spacing for nixpkgs.url regardless of the version number
    sed -i 's/nixpkgs.url = "/nixpkgs.url      =                "/' "$NIXOS_PATH/core/flake.nix"

    # 5. Shellcheck (Shell Script Analysis)
    log_msg "Task" "Step 5: Shell script static analysis (shellcheck)"
    log_exec "nix" ">" "shellcheck"
    # Temporarily set +e so shellcheck errors don't crash the script immediately
    set +e
    nix-shell -p shellcheck --run "shellcheck $NIXOS_PATH/core/scripts/*.sh $NIXOS_PATH/from-nixos-mk-iso.sh"
    SHELLCHECK_RESULT=$?
    set -e
    
    if [ $SHELLCHECK_RESULT -ne 0 ]; then
        log_exec "nix" "<" "shellcheck"
        log_msg "Error" "Shellcheck failed! Please fix syntax risks in shell scripts."
        exit 1
    fi
    log_exec "nix" "<" "shellcheck"

    # 6. Integrity Verification (nix flake check)
    log_msg "Task" "Step 6: Final build integrity verification (nix flake check)"
    TMP_VERIFY_DIR="/tmp/nhw-verify-$(date +%s)"
    mkdir -p "$TMP_VERIFY_DIR"

    # Copy necessary sources
    cp -a "$NIXOS_PATH/core/"* "$TMP_VERIFY_DIR/"
    cp -a "$NIXOS_PATH/hosts" "$TMP_VERIFY_DIR/"
    cp -a "$NIXOS_PATH/mods" "$TMP_VERIFY_DIR/"

    # Resolve host JSON files → TMP_VERIFY_DIR/resolved.json
    log_msg "Task" "Step 6a: Resolving host JSON files"
    python3 "$SCRIPT_DIR/nhw.resolve.py" "$TMP_VERIFY_DIR"

    # Use the determined host's lock file for verification
    if [ -f "$HOST_SPECIFIC_LOCK" ]; then
        cp "$HOST_SPECIFIC_LOCK" "$TMP_VERIFY_DIR/flake.lock"
        log_msg "Task" "Using lock file: $(basename "$HOST_SPECIFIC_LOCK")"
    fi

    cd "$TMP_VERIFY_DIR"
    log_exec "nix" ">" "nix flake check"
    if nix flake check . --allow-import-from-derivation --extra-experimental-features 'nix-command flakes'; then
        log_exec "nix" "<" "nix flake check"
        log_msg "Done" "All verifications passed successfully!"
        rm -rf "$TMP_VERIFY_DIR"
    else
        log_exec "nix" "<" "nix flake check"
        log_msg "Error" "Verification failed! Check temporary directory: $TMP_VERIFY_DIR"
        exit 1
    fi
}

# Redirect to nhw dispatcher when run standalone
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "redirecting to nhw dispatcher..."
    exec nhw check "$@"
fi

run_check_task
