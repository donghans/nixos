#!/usr/bin/env bash

run_fix_task() {
    local pkg_names=("$@")
    
    if [ ${#pkg_names[@]} -eq 0 ]; then
        log_msg "Error" "provide package names."
        exit 1
    fi

    local repo="NixOS/nixpkgs"
    local earliest_timestamp=9999999999
    local final_rev=""
    local final_date=""

    log_msg "Task" "searching safest common commit for: ${pkg_names[*]}"

    for pkg_name in "${pkg_names[@]}"; do
        echo "   - processing '$pkg_name'..."
        
        local search_path
        search_path=$(curl -s "https://api.github.com/search/code?q=filename:package.nix+path:pkgs/by-name/**/${pkg_name}+repo:${repo}" | jq -r '.items[0].path')
        if [ "$search_path" == "null" ] || [ -z "$search_path" ]; then
            search_path=$(curl -s "https://api.github.com/search/code?q=filename:default.nix+${pkg_name}+path:pkgs/**+repo:${repo}" | jq -r '.items[0].path')
        fi

        if [ "$search_path" == "null" ] || [ -z "$search_path" ]; then
            log_msg "Warn" "path not found for '$pkg_name'. skipping."
            continue
        fi

        local commits
        commits=$(curl -s "https://api.github.com/repos/${repo}/commits?path=${search_path}&sha=nixos-unstable")
        local safe_fallback_commit
        safe_fallback_commit=$(echo "$commits" | jq -r '.[1].sha') 
        local commit_date
        commit_date=$(echo "$commits" | jq -r '.[1].commit.committer.date')
        local timestamp
        timestamp=$(date -d "$commit_date" +%s)

        if [ -z "$safe_fallback_commit" ] || [ "$safe_fallback_commit" == "null" ]; then
            log_msg "Warn" "history not found for '$pkg_name'. skipping."
            continue
        fi

        if [ "$timestamp" -lt "$earliest_timestamp" ]; then
            earliest_timestamp=$timestamp
            final_rev=$safe_fallback_commit
            final_date=$commit_date
        fi
    done

    if [ -z "$final_rev" ]; then
        log_msg "Error" "could not find any valid commits."
        exit 1
    fi

    log_msg "Info" "safe commit selected: $final_rev ($final_date)"
    
    local tarball_url="https://github.com/${repo}/archive/${final_rev}.tar.gz"
    local sha256
    sha256=$(nix-prefetch-url --unpack "$tarball_url" 2>/dev/null || true)
    local sri_hash
    sri_hash=$(nix hash to-sri --type sha256 "$sha256" || true)

    update_env_file "$ENV_FILE" "UNSTABLE_FALLBACK_REV" "$final_rev"
    update_env_file "$ENV_FILE" "UNSTABLE_FALLBACK_SHA" "$sri_hash"

    log_msg "Done" "UNSTABLE_FALLBACK updated in .env"
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    log_msg "Notice" "redirecting to nhw fix-unstable..."
    exec nhw fix-unstable "$@"
fi

run_fix_task "${EXTRA_ARGS[@]}"
