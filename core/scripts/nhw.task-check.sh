#!/usr/bin/env bash
# core/scripts/nhw.task-check.sh
# Integrated task for project code integrity verification and anti-pattern cleanup

run_check_task() {
    # 1. Dead code check (deadnix)
    log_msg "Task" "Step 1: Searching for unused code (deadnix)"
    log_exec "nix" ">" "deadnix"
    deadnix "$NIXOS_PATH"
    log_exec "nix" "<" "deadnix"

    # 2. Anti-pattern fix (statix fix)
    log_msg "Task" "Step 2: Auto-fixing anti-patterns (statix fix)"
    log_exec "nix" ">" "statix fix"
    statix fix "$NIXOS_PATH"
    log_exec "nix" "<" "statix fix"

    # 3. Code Formatting (alejandra)
    log_msg "Task" "Step 3: Formatting code (alejandra)"
    log_exec "nix" ">" "alejandra"
    alejandra -q "$NIXOS_PATH"
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
    shellcheck "$NIXOS_PATH/core/scripts/"*.sh "$NIXOS_PATH/from-nixos-mk-iso.sh"
    SHELLCHECK_RESULT=$?
    set -e

    if [ $SHELLCHECK_RESULT -ne 0 ]; then
        log_exec "nix" "<" "shellcheck"
        log_msg "Error" "Shellcheck failed! Please fix syntax risks in shell scripts."
        exit 1
    fi
    log_exec "nix" "<" "shellcheck"

    # 6. Integrity Verification
    # 기본: 현재 호스트만 nix eval (빠름)
    # --deep: 전체 호스트 nix flake check + eval 캐시 (.verify git 기반)
    VERIFY_DIR="$NIXOS_PATH/.verify"
    NIX_EVAL_FLAGS=(--allow-import-from-derivation --extra-experimental-features 'nix-command flakes')

    # 공통: verify 환경 준비 (양쪽 모드 동일)
    if [ -f "$HOST_SPECIFIC_LOCK" ]; then
        log_msg "Task" "Using lock file: $(basename "$HOST_SPECIFIC_LOCK")"
    fi
    prepare_verify_dir "$NIXOS_PATH" "$VERIFY_DIR" "$JSON_DIR" "$HOST_SPECIFIC_LOCK"

    if [ "$CHECK_DEEP" = true ]; then
        log_msg "Task" "Step 6: Full integrity check via nix flake check (all hosts)"
        log_exec "nix" ">" "nix flake check"
        if nix flake check "$VERIFY_DIR" "${NIX_EVAL_FLAGS[@]}"; then
            log_exec "nix" "<" "nix flake check"
            log_msg "Done" "All verifications passed successfully!"
        else
            log_exec "nix" "<" "nix flake check"
            log_msg "Error" "Verification failed! (inspect: $VERIFY_DIR)"
            exit 1
        fi
    else
        log_msg "Task" "Step 6: Integrity check via nix eval (nixosConfigurations.${HOST_ID})"
        EVAL_FAILED=false

        log_exec "nix" ">" "nixosConfigurations.${HOST_ID}"
        if nix eval "${VERIFY_DIR}#nixosConfigurations.${HOST_ID}.config.system.build.toplevel" \
            --apply "drv: drv.drvPath" \
            "${NIX_EVAL_FLAGS[@]}"; then
            log_exec "nix" "<" "nixosConfigurations.${HOST_ID}"
        else
            log_exec "nix" "<" "nixosConfigurations.${HOST_ID}"
            log_msg "Error" "nixosConfigurations.${HOST_ID} failed!"
            EVAL_FAILED=true
        fi

        # 현재 호스트에 속한 homeConfigurations (*@HOST_ID) 순회
        HOME_HOSTS=$(nix eval "${VERIFY_DIR}#homeConfigurations" \
            --apply "cfgs: builtins.concatStringsSep \"\n\" (builtins.filter (k: builtins.match (\".*@${HOST_ID}\") k != null) (builtins.attrNames cfgs))" \
            --raw \
            --extra-experimental-features 'nix-command flakes')

        while IFS= read -r host; do
            [ -z "$host" ] && continue
            log_exec "nix" ">" "homeConfigurations.${host}"
            if nix eval "${VERIFY_DIR}#homeConfigurations.\"${host}\".activationPackage" \
                --apply "pkg: pkg.drvPath" \
                "${NIX_EVAL_FLAGS[@]}"; then
                log_exec "nix" "<" "homeConfigurations.${host}"
            else
                log_exec "nix" "<" "homeConfigurations.${host}"
                log_msg "Error" "homeConfigurations.${host} failed!"
                EVAL_FAILED=true
            fi
        done <<< "$HOME_HOSTS"

        if [ "$EVAL_FAILED" = true ]; then
            log_msg "Error" "Verification failed! (inspect: $VERIFY_DIR)"
            exit 1
        fi
        log_msg "Done" "All verifications passed successfully!"
    fi
}

# Redirect to nhw dispatcher when run standalone
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "redirecting to nhw dispatcher..."
    exec nhw check "$@"
fi

run_check_task
