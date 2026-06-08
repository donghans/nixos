#!/usr/bin/env bash
# rnixup.task-deploy.sh — 원격 NixOS 호스트 전체 배포 (deploy-rs)
#
# deploy.nodes 전체를 deploy-rs 네이티브 병렬로 배포.
# 변수 의존: BUILD_DIR, JSON_DIR
# shellcheck disable=SC1091
source "$(dirname "${BASH_SOURCE[0]}")/rnixup.lib-secrets.sh"


# ── SSH 키 파일 누락 사전 확인 ────────────────────────────────────────────────
# ~/.ssh/rnixup/.hostignore에 없는 호스트 중 sshKey 파일이 없으면 일괄 안내.
_check_ssh_keys() {
    local hostignore="$HOME/.ssh/rnixup/.hostignore"
    local resolved_json="$JSON_DIR/resolved.json"
    local rnixup_dir="$HOME/.ssh/rnixup"
    local -a _missing_hosts=() _missing_keys=()
    local -a _remain_hosts=() _remain_keys=() _check_args=()
    local _choice _src _ignored _selected sel hostname i

    while IFS=$'\t' read -r hostname keypath; do
        [ -z "$hostname" ] && continue
        # 단일 호스트 모드: 대상 외 스킵
        [ -n "${DEPLOY_NODE:-}" ] && [ "$hostname" != "$DEPLOY_NODE" ] && continue
        # .hostignore에 등록된 호스트는 스킵
        if [ -f "$hostignore" ] && grep -qxF "$hostname" "$hostignore" 2>/dev/null; then
            continue
        fi
        local expanded="${keypath/#\~/$HOME}"
        if [ ! -f "$expanded" ]; then
            _missing_hosts+=("$hostname")
            _missing_keys+=("$expanded")
        fi
    done < <(jq -r '
        to_entries[]
        | select(.value.deploy != null and (.value.deploy.sshKey // "") != "")
        | [.key, .value.deploy.sshKey]
        | @tsv
    ' "$resolved_json")

    [ "${#_missing_hosts[@]}" -eq 0 ] && return

    while [ "${#_missing_hosts[@]}" -gt 0 ]; do
        # 누락 목록 출력
        printf "\n"
        log_msg "Warn" "SSH 키 파일이 없는 호스트 (${#_missing_hosts[@]}개):"
        for i in "${!_missing_hosts[@]}"; do
            printf "  ${YELLOW}%-28s${NC} → %s\n" "${_missing_hosts[$i]}" "${_missing_keys[$i]}"
        done
        printf "\n"
        read -rp "$(_log_prompt)처리 방법: [c]opy 경로 지정  /  [q]uit  /  [i]gnore 다시 묻지 않음: " _choice

        case "${_choice:-q}" in
            c|C)
                mkdir -p "$rnixup_dir"
                chmod 700 "$rnixup_dir"
                # 복사할 호스트 선택 (선택 없이 Enter → 뒤로가기)
                _check_args=()
                for i in "${!_missing_hosts[@]}"; do
                    _check_args+=("${_missing_hosts[$i]}" "${_missing_hosts[$i]}  →  ${_missing_keys[$i]}")
                done
                log_msg "Notice" "선택 없이 Enter = 뒤로가기"
                _check "복사할 호스트를 선택하세요" "${_check_args[@]}"
                [ "${#REPLY_CHECKED[@]}" -eq 0 ] && continue
                # 선택된 호스트마다 순서대로 경로 입력
                _remain_hosts=(); _remain_keys=()
                for i in "${!_missing_hosts[@]}"; do
                    _selected=false
                    for sel in "${REPLY_CHECKED[@]}"; do
                        [ "${_missing_hosts[$i]}" = "$sel" ] && _selected=true && break
                    done
                    if [ "$_selected" = false ]; then
                        _remain_hosts+=("${_missing_hosts[$i]}")
                        _remain_keys+=("${_missing_keys[$i]}")
                        continue
                    fi
                    printf "\n"
                    read -rep "$(_log_prompt_rl)${_missing_hosts[$i]} 키 파일 원본 경로 (Tab 자동완성, 빈 줄=건너뜀): " _src
                    if [ -z "$_src" ]; then
                        log_msg "Notice" "건너뜀: ${_missing_hosts[$i]}"
                        _remain_hosts+=("${_missing_hosts[$i]}")
                        _remain_keys+=("${_missing_keys[$i]}")
                    else
                        _src="${_src/#\~/$HOME}"
                        if [ ! -f "$_src" ]; then
                            log_msg "Error" "파일 없음: $_src"
                            _remain_hosts+=("${_missing_hosts[$i]}")
                            _remain_keys+=("${_missing_keys[$i]}")
                        else
                            cp "$_src" "${_missing_keys[$i]}"
                            chmod 600 "${_missing_keys[$i]}"
                            log_msg "Done" "복사 완료: ${_missing_keys[$i]}"
                        fi
                    fi
                done
                _missing_hosts=("${_remain_hosts[@]+"${_remain_hosts[@]}"}")
                _missing_keys=("${_remain_keys[@]+"${_remain_keys[@]}"}")
                ;;
            i|I)
                # _check UI: ignore할 호스트 복수 선택
                _check_args=()
                for i in "${!_missing_hosts[@]}"; do
                    _check_args+=("${_missing_hosts[$i]}" "${_missing_hosts[$i]}  →  ${_missing_keys[$i]}")
                done
                _check "ignore할 호스트를 선택하세요" "${_check_args[@]}"
                if [ "${#REPLY_CHECKED[@]}" -gt 0 ]; then
                    mkdir -p "$rnixup_dir"
                    for hostname in "${REPLY_CHECKED[@]}"; do
                        echo "$hostname" >> "$hostignore"
                    done
                    log_msg "Done" ".hostignore에 추가: ${REPLY_CHECKED[*]}"
                    # 선택된 호스트 목록에서 제거
                    _remain_hosts=(); _remain_keys=()
                    for i in "${!_missing_hosts[@]}"; do
                        _ignored=false
                        for sel in "${REPLY_CHECKED[@]}"; do
                            [ "${_missing_hosts[$i]}" = "$sel" ] && _ignored=true && break
                        done
                        [ "$_ignored" = false ] && {
                            _remain_hosts+=("${_missing_hosts[$i]}")
                            _remain_keys+=("${_missing_keys[$i]}")
                        }
                    done
                    _missing_hosts=("${_remain_hosts[@]+"${_remain_hosts[@]}"}")
                    _missing_keys=("${_remain_keys[@]+"${_remain_keys[@]}"}")
                fi
                ;;
            *)
                log_msg "Notice" "취소. 키 파일을 직접 복사 후 rnixup을 재실행하세요:"
                for i in "${!_missing_hosts[@]}"; do
                    log_msg "Notice" "  cp <source> ${_missing_keys[$i]}"
                done
                exit 0
                ;;
        esac
    done
}

_run_deploy_task() {
    local resolved_json="$JSON_DIR/resolved.json"

    local deploy_count
    deploy_count=$(jq '[to_entries[] | select(.value.deploy != null)] | length' "$resolved_json")

    if [ "$deploy_count" -eq 0 ]; then
        log_msg "Error" "deploy 가능한 호스트가 없습니다."
        log_msg "Notice" "hosts/*.toml에 [deploy] 섹션을 추가하거나, 새 호스트라면 rnixstrap을 사용하세요."
        exit 1
    fi

    # 단일 호스트 모드: 존재 확인 후 카운트 재설정
    local _deploy_label
    if [ -n "${DEPLOY_NODE:-}" ]; then
        local _node_exists
        _node_exists=$(jq -r --arg h "$DEPLOY_NODE" '.[$h].deploy // empty' "$resolved_json")
        if [ -z "$_node_exists" ]; then
            log_msg "Error" "호스트 '$DEPLOY_NODE'를 찾을 수 없습니다. 'rnixup list'로 확인하세요."
            exit 1
        fi
        deploy_count=1
        _deploy_label="$DEPLOY_NODE"
    else
        _deploy_label="all nodes"
    fi

    _check_ssh_keys

    # ── dry-activate ──────────────────────────────────────────────────────────
    local _deploy_target="path:${BUILD_DIR}"
    [ -n "${DEPLOY_NODE:-}" ] && _deploy_target="path:${BUILD_DIR}#${DEPLOY_NODE}"

    log_msg "Task" "원격 호스트 ${deploy_count}개 dry-activate 중..."
    log_exec "d-rs" ">" "dry-activate"
    nix run "github:serokell/deploy-rs" -- \
        --skip-checks \
        --dry-activate \
        "$_deploy_target"
    log_exec "d-rs" "<" "dry-activate"

    # ── 배포 확인 ─────────────────────────────────────────────────────────────
    printf "\n"
    read -rp "$(_log_prompt)위 변경사항을 배포하시겠습니까? (Y/n): " _confirm
    _confirm="${_confirm:-Y}"
    if [[ ! "$_confirm" =~ ^[Yy]$ ]]; then
        log_msg "Notice" "배포 취소됨."
        exit 0
    fi

    # dry-activate + 사용자 확인 완료 후부터 시간 측정
    _START_TIME=$(date +%s)
    _START_TIME_STR=$(date "+%Y-%m-%d %H:%M:%S")

    # ── 시크릿 주입 (선택) ────────────────────────────────────────────────────
    if _any_remote_secrets_exist; then
        printf "\n"
        read -rp "$(_log_prompt)시크릿을 서버에 주입하시겠습니까? (y/N): " _inject
        if [[ "${_inject:-N}" =~ ^[Yy]$ ]]; then
            inject_all_remote_secrets
        else
            log_msg "Notice" "시크릿 주입 건너뜀."
        fi
    fi

    # ── Preauth key 생성·배포 (선택) ─────────────────────────────────────────
    if _any_remote_preauth_keys_needed; then
        printf "\n"
        read -rp "$(_log_prompt)Preauth key를 생성/배포하시겠습니까? (y/N): " _inject_preauth
        if [[ "${_inject_preauth:-N}" =~ ^[Yy]$ ]]; then
            check_all_preauth_keys_remote
        else
            log_msg "Notice" "Preauth key 생성 건너뜀."
        fi
    fi

    # ── 실제 배포 ─────────────────────────────────────────────────────────────
    log_msg "Task" "$deploy_count remote host(s) 배포 시작..."
    log_exec "d-rs" ">" "$_deploy_label"
    nix run "github:serokell/deploy-rs" -- \
        --skip-checks \
        "$_deploy_target"
    log_exec "d-rs" "<" "$_deploy_label"
    log_msg "Done" "$deploy_count 호스트 배포 완료"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "rnixup으로 전달 중..."
    exec rnixup
fi

_run_deploy_task
