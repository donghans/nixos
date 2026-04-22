#!/usr/bin/env bash

run_fix_task() {
    local pkg_names=("$@")
    
    if [ ${#pkg_names[@]} -eq 0 ]; then
        log_msg "Error" "패키지 이름을 입력하세요."
        exit 1
    fi

    local repo="NixOS/nixpkgs"
    local earliest_timestamp=9999999999
    local final_rev=""
    local final_date=""

    log_msg "Task" "가장 안전한 공통 커밋 탐색 중: ${pkg_names[*]}"

    for pkg_name in "${pkg_names[@]}"; do
        log_msg "Notice" "'$pkg_name' 처리 중..."
        
        local search_path api_result
        api_result=$(gh api "search/code?q=filename:package.nix+path:pkgs/by-name/**/${pkg_name}+repo:${repo}") || {
            log_msg "Warn" "'$pkg_name' GitHub API 실패. 건너뜁니다."
            continue
        }
        search_path=$(echo "$api_result" | jq -r '.items[0].path')
        if [ "$search_path" == "null" ] || [ -z "$search_path" ]; then
            api_result=$(gh api "search/code?q=filename:default.nix+${pkg_name}+path:pkgs/**+repo:${repo}") || {
                log_msg "Warn" "'$pkg_name' GitHub API 실패. 건너뜁니다."
                continue
            }
            search_path=$(echo "$api_result" | jq -r '.items[0].path')
        fi

        if [ "$search_path" == "null" ] || [ -z "$search_path" ]; then
            log_msg "Warn" "'$pkg_name' 경로를 찾을 수 없습니다. 건너뜁니다."
            continue
        fi

        local commits
        commits=$(gh api "repos/${repo}/commits?path=${search_path}&sha=nixos-unstable") || {
            log_msg "Warn" "'$pkg_name' 커밋 GitHub API 실패. 건너뜁니다."
            continue
        }

        local commit_count
        commit_count=$(echo "$commits" | jq 'length')

        local safe_fallback_commit commit_date
        if [ "$commit_count" -ge 2 ]; then
            safe_fallback_commit=$(echo "$commits" | jq -r '.[1].sha')
            commit_date=$(echo "$commits" | jq -r '.[1].commit.committer.date')
        elif [ "$commit_count" -eq 1 ]; then
            log_msg "Warn" "'$pkg_name' 커밋이 1개뿐 — 그대로 사용합니다."
            safe_fallback_commit=$(echo "$commits" | jq -r '.[0].sha')
            commit_date=$(echo "$commits" | jq -r '.[0].commit.committer.date')
        else
            log_msg "Warn" "'$pkg_name' 커밋을 찾을 수 없습니다. 건너뜁니다."
            continue
        fi

        if [ -z "$safe_fallback_commit" ] || [ -z "$commit_date" ]; then
            log_msg "Warn" "'$pkg_name' 히스토리를 찾을 수 없습니다. 건너뜁니다."
            continue
        fi

        # Requires GNU date (coreutils)
        local timestamp
        timestamp=$(date -d "$commit_date" +%s)

        if [ "$timestamp" -lt "$earliest_timestamp" ]; then
            earliest_timestamp=$timestamp
            final_rev=$safe_fallback_commit
            final_date=$commit_date
        fi
    done

    if [ -z "$final_rev" ]; then
        log_msg "Error" "유효한 커밋을 찾을 수 없습니다."
        exit 1
    fi

    log_msg "Done" "안전한 커밋 선택: $final_rev ($final_date)"
    
    local tarball_url="https://github.com/${repo}/archive/${final_rev}.tar.gz"
    local sha256
    sha256=$(nix-prefetch-url --unpack "$tarball_url" 2>/dev/null) || {
        log_msg "Error" "tarball 사전 다운로드 실패."
        exit 1
    }
    local sri_hash
    sri_hash=$(nix hash to-sri --type sha256 "$sha256") || {
        log_msg "Error" "SRI 해시 계산 실패."
        exit 1
    }

    update_env_file "$ENV_FILE" "NIX_UNSTABLE_FALLBACK_REV" "$final_rev"
    update_env_file "$ENV_FILE" "NIX_UNSTABLE_FALLBACK_SHA" "$sri_hash"

    log_msg "Done" ".env의 NIX_UNSTABLE_FALLBACK 업데이트 완료"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "nixup fix로 전달 중..."
    exec nixup fix "$@"
fi

run_fix_task "${EXTRA_ARGS[@]}"
