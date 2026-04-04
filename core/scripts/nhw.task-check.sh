# core/scripts/nhw.task-check.sh
# 프로젝트 코드 무결성 검증 및 안티패턴 정리 통합 태스크

run_check_task() {
    # 1. Dead code check (deadnix)
    log_msg "Task" "1단계: 사용되지 않는 코드 탐색 (deadnix)"
    log_exec "nix" ">" "deadnix"
    nix-shell -p deadnix --run "deadnix $NIXOS_PATH"
    log_exec "nix" "<" "done"

    # 2. Anti-pattern fix (statix)
    log_msg "Task" "2단계: 안티패턴 자동 수정 (statix fix)"
    log_exec "nix" ">" "statix fix"
    nix-shell -p statix --run "statix fix $NIXOS_PATH"
    log_exec "nix" "<" "done"

    # 3. Code Formatting (alejandra)
    log_msg "Task" "3단계: 코드 포맷팅 (alejandra)"
    log_exec "nix" ">" "alejandra"
    nix-shell -p alejandra --run "alejandra -q $NIXOS_PATH"
    log_exec "nix" "<" "done"

    # 4. Exception Handling (flake.nix spacing)
    log_msg "Task" "4단계: 특수 예외 처리 (flake.nix 정렬 복원)"
    # 25.11 등 버전 숫자에 상관없이 nixpkgs.url의 정렬을 강제로 복원합니다.
    sed -i 's/nixpkgs.url = "/nixpkgs.url      =                "/' "$NIXOS_PATH/core/flake.nix"

    # 5. Integrity Verification (nix flake check)
    log_msg "Task" "5단계: 빌드 무결성 최종 검증 (nix flake check)"
    TMP_VERIFY_DIR="/tmp/nhw-verify-$(date +%s)"
    mkdir -p "$TMP_VERIFY_DIR"

    # 필요한 소스 복사
    cp -a "$NIXOS_PATH/core/"* "$TMP_VERIFY_DIR/"
    cp -a "$NIXOS_PATH/dev" "$TMP_VERIFY_DIR/"
    cp -a "$NIXOS_PATH/lib" "$TMP_VERIFY_DIR/"

    # 결정된 호스트의 락 파일을 가져가서 검증
    if [ -f "$HOST_SPECIFIC_LOCK" ]; then
        cp "$HOST_SPECIFIC_LOCK" "$TMP_VERIFY_DIR/flake.lock"
        log_msg "Task" "사용한 락 파일: $(basename "$HOST_SPECIFIC_LOCK")"
    fi

    cd "$TMP_VERIFY_DIR"
    log_exec "nix" ">" "flake check"
    if nix flake check . --allow-import-from-derivation --extra-experimental-features 'nix-command flakes'; then
        log_exec "nix" "<" "success"
        log_msg "Done" "모든 검증을 통과했습니다!"
        rm -rf "$TMP_VERIFY_DIR"
    else
        log_exec "nix" "<" "failed"
        log_msg "Error" "검증 실패! 임시 디렉토리를 확인하세요: $TMP_VERIFY_DIR"
        exit 1
    fi
}

# 단독 실행 시 nhw 디스패처로 리다이렉트
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "redirecting to nhw dispatcher..."
    exec nhw check "$@"
fi

run_check_task
