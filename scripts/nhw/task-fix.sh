#!/usr/bin/env bash

run_fix_task() {
    # nhw.sh에서 넘겨준 가변 인자(패키지 목록) 사용
    local pkg_names=("$@")
    
    if [ ${#pkg_names[@]} -eq 0 ]; then
        echo "❌ Error: 복구할 패키지 이름을 입력해주세요."
        echo "   Usage: ./nhw.sh fix-unstable [pkg1] [pkg2] ..."
        exit 1
    fi

    local repo="NixOS/nixpkgs"
    local oldest_timestamp=9999999999
    local final_rev=""
    local final_date=""

    echo "🔍 Searching for the safest common stable commit for: ${pkg_names[*]} ..."

    for pkg_name in "${pkg_names[@]}"; do
        echo "   - Processing '$pkg_name'..."
        
        # 패키지 경로 찾기
        local search_path=$(curl -s "https://api.github.com/search/code?q=filename:package.nix+path:pkgs/by-name/**/${pkg_name}+repo:${repo}" | jq -r '.items[0].path')
        if [ "$search_path" == "null" ] || [ -z "$search_path" ]; then
            search_path=$(curl -s "https://api.github.com/search/code?q=filename:default.nix+${pkg_name}+path:pkgs/**+repo:${repo}" | jq -r '.items[0].path')
        fi

        if [ "$search_path" == "null" ] || [ -z "$search_path" ]; then
            echo "   ⚠️  Warning: '$pkg_name' 경로를 찾을 수 없습니다. 건너뜁니다."
            continue
        fi

        # 커밋 히스토리 조회 (unstable 브랜치)
        local commits=$(curl -s "https://api.github.com/repos/${repo}/commits?path=${search_path}&sha=nixos-unstable")
        local good_commit=$(echo "$commits" | jq -r '.[1].sha') 
        local commit_date=$(echo "$commits" | jq -r '.[1].commit.committer.date')
        local timestamp=$(date -d "$commit_date" +%s)

        if [ -z "$good_commit" ] || [ "$good_commit" == "null" ]; then
            echo "   ⚠️  Warning: '$pkg_name' 히스토리를 찾을 수 없습니다. 건너뜁니다."
            continue
        fi

        if [ "$timestamp" -lt "$oldest_timestamp" ]; then
            oldest_timestamp=$timestamp
            final_rev=$good_commit
            final_date=$commit_date
        fi
    done

    if [ -z "$final_rev" ]; then
        echo "❌ Error: 유효한 커밋을 찾지 못했습니다."
        exit 1
    fi

    echo "🎯 Selected safest common REV: $final_rev ($final_date)"
    
    # SRI Hash 계산
    local tarball_url="https://github.com/${repo}/archive/${final_rev}.tar.gz"
    local sha256=$(nix-prefetch-url --unpack "$tarball_url" 2>/dev/null)
    local sri_hash=$(nix hash to-sri --type sha256 "$sha256")

    # .env 업데이트 (lib-build.sh의 함수 활용)
    update_env_file "$ENV_FILE" "UNSTABLE_FALLBACK_REV" "$final_rev"
    update_env_file "$ENV_FILE" "UNSTABLE_FALLBACK_SHA" "$sri_hash"

    echo -e "\n✨ Successfully updated UNSTABLE_FALLBACK in .env"
    echo "   REV: $final_rev"
    echo "   SHA: $sri_hash"
}

# 직접 실행 시 리다이렉트
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    echo "⚠️  직접 실행 감지: nhw.sh fix-unstable 환경으로 전환합니다..."
    exec "$(dirname "$0")/../../nhw.sh" fix-unstable "$@"
fi

# nhw.sh에서 넘겨준 나머지 인자들(패키지명)을 함수로 전달
run_fix_task "${EXTRA_ARGS[@]}"
