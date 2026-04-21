#!/usr/bin/env bash
# core/scripts/nixup.task-check.sh
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
    # (목적: core/flake.nix는 inputs 정렬이 의도적이므로 포맷 대상 제외)
    log_msg "Task" "Step 3: Formatting code (alejandra, excluding core/flake.nix)"
    log_exec "nix" ">" "alejandra"
    find "$NIXOS_PATH" -name "*.nix" ! -path "$NIXOS_PATH/core/flake.nix" -print0 \
        | xargs -0 alejandra -q
    log_exec "nix" "<" "alejandra"

    # 4. Shellcheck (Shell Script Analysis)
    log_msg "Task" "Step 4: Shell script static analysis (shellcheck)"
    log_exec "nix" ">" "shellcheck"
    # Temporarily set +e so shellcheck errors don't crash the script immediately
    set +e
    shellcheck "$NIXOS_PATH/core/scripts/"*.sh "$NIXOS_PATH/nixstrap.sh" "$NIXOS_PATH/nixup-iso.sh"
    SHELLCHECK_RESULT=$?
    set -e

    if [ $SHELLCHECK_RESULT -ne 0 ]; then
        log_exec "nix" "<" "shellcheck"
        log_msg "Error" "Shellcheck failed! Please fix syntax risks in shell scripts."
        exit 1
    fi
    log_exec "nix" "<" "shellcheck"

    # 5. Integrity Verification
    # 기본: 전체 호스트 nix flake check (완전 검증)
    # --fast: 현재 호스트만 nix eval (빠름)
    NIX_EVAL_FLAGS=(--allow-import-from-derivation "${NIX_FLAKE_FLAGS[@]}")

    # 공통: build 환경 준비 (양쪽 모드 동일)
    if [ -f "$HOST_SPECIFIC_LOCK" ]; then
        log_msg "Task" "Using lock file: $(basename "$HOST_SPECIFIC_LOCK")"
    fi
    prepare_build_dir "$NIXOS_PATH" "$BUILD_DIR" "$ENV_FILE" "$HOST_SPECIFIC_LOCK"

    if [ "${CHECK_FAST:-false}" = true ]; then
        log_msg "Task" "Step 5: Integrity check via nix eval (nixosConfigurations.${HOST_ID})"
        EVAL_FAILED=false

        log_exec "nix" ">" "nixosConfigurations.${HOST_ID}"
        if nix eval "path:${BUILD_DIR}#nixosConfigurations.${HOST_ID}.config.system.build.toplevel" \
            --apply "drv: drv.drvPath" \
            "${NIX_EVAL_FLAGS[@]}"; then
            log_exec "nix" "<" "nixosConfigurations.${HOST_ID}"
        else
            log_exec "nix" "<" "nixosConfigurations.${HOST_ID}"
            log_msg "Error" "nixosConfigurations.${HOST_ID} failed!"
            EVAL_FAILED=true
        fi

        # 현재 호스트에 속한 homeConfigurations (*@HOST_ID) 순회
        HOME_HOSTS=$(nix eval "path:${BUILD_DIR}#homeConfigurations" \
            --apply "cfgs: let s = \"@${HOST_ID}\"; n = builtins.stringLength s; in builtins.concatStringsSep \"\n\" (builtins.filter (k: let l = builtins.stringLength k; in l >= n && builtins.substring (l - n) n k == s) (builtins.attrNames cfgs))" \
            --raw \
            "${NIX_FLAKE_FLAGS[@]}")

        while IFS= read -r host; do
            [ -z "$host" ] && continue
            log_exec "nix" ">" "homeConfigurations.${host}"
            if nix eval "path:${BUILD_DIR}#homeConfigurations.\"${host}\".activationPackage" \
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
            log_msg "Error" "Verification failed! (inspect: $BUILD_DIR)"
            exit 1
        fi
        log_msg "Done" "All verifications passed successfully!"
    else
        log_msg "Task" "Step 5: Full integrity check via nix flake check (all hosts)"
        log_exec "nix" ">" "nix flake check"
        if nix flake check "path:$BUILD_DIR" "${NIX_EVAL_FLAGS[@]}"; then
            log_exec "nix" "<" "nix flake check"
            log_msg "Done" "All verifications passed successfully!"
        else
            log_exec "nix" "<" "nix flake check"
            log_msg "Error" "Verification failed! (inspect: $BUILD_DIR)"
            exit 1
        fi
    fi
}

# Redirect to nixup dispatcher when run standalone
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "redirecting to nixup dispatcher..."
    exec nixup check "$@"
fi

run_check_task
