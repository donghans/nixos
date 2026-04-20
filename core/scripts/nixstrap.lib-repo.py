#!/usr/bin/env python3
"""nixstrap.lib-repo.py — nixstrap.sh용 레포지토리/설정 서브커맨드 헬퍼

서브커맨드:
  check-repo   <repo_tmp>             → base.toml에서 git.nixosRepo 출력
  update-repo  <repo_tmp> <new_repo>  → base.toml의 git.nixosRepo를 in-place 수정
  sync-remote  <repo_path>            → git remote origin에서 owner/repo 자동 감지 후 base.toml 동기화
  username     <repo_tmp>             → base.toml에서 username 출력
  list-hosts   <repo_tmp>             → hostname|type|preset 형식으로 호스트 목록 출력
  list-presets <repo_tmp>             → 프리셋 이름 출력 (iso 제외)
  disk-labels  <repo_tmp> <host>      → BOOT_LABEL DISK_LABEL 출력 (공백 구분)
"""

import sys
import os
import re
import tomllib


def cmd_check_repo(args):
    repo_tmp = args[0]
    base_path = os.path.join(repo_tmp, "hosts", "_base.toml")
    try:
        with open(base_path, "rb") as f:
            base = tomllib.load(f)
        print(base.get("git", {}).get("nixosRepo", ""))
    except Exception:
        print("")


def _update_field(toml_path, pattern, new_value):
    """_base.toml에서 정규식 패턴에 일치하는 값을 in-place 수정."""
    with open(toml_path, "r") as f:
        content = f.read()
    content = re.sub(pattern, f'\\g<1>{new_value}\\g<2>', content)
    with open(toml_path, "w") as f:
        f.write(content)


def _fetch_github_user(owner):
    """GitHub API로 사용자 정보 조회. 실패 시 None 반환.
    email이 비공개인 경우 {id}+{login}@users.noreply.github.com으로 구성."""
    import urllib.request
    import json
    try:
        req = urllib.request.Request(
            f"https://api.github.com/users/{owner}",
            headers={"Accept": "application/vnd.github+json", "User-Agent": "nixstrap"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        name  = data.get("name") or ""
        email = data.get("email") or ""
        uid   = data.get("id")
        login = data.get("login", owner)
        if not email and uid:
            email = f"{uid}+{login}@users.noreply.github.com"
        return {"name": name, "email": email}
    except Exception:
        return None


def cmd_sync_remote(args):
    """git remote origin URL에서 owner/repo를 추출하여 base.toml을 자동 동기화."""
    import subprocess
    repo_path = args[0]

    # git remote get-url origin
    try:
        remote_url = subprocess.check_output(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_path, text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return  # remote 없거나 git 없으면 skip

    # https://github.com/owner/repo.git  또는  git@github.com:owner/repo.git → owner/repo
    m = re.search(r"[:/]([^/:][^/]*/[^/]+?)(?:\.git)?$", remote_url)
    if not m:
        return  # 형식 불명 — skip

    detected = m.group(1)

    # 현재 base.toml 값과 비교
    base_path = os.path.join(repo_path, "hosts", "_base.toml")
    try:
        with open(base_path, "rb") as f:
            base = tomllib.load(f)
        current = base.get("git", {}).get("nixosRepo", "")
    except Exception:
        return

    if current == detected:
        return  # 이미 일치

    cmd_update_repo([repo_path, detected])
    print(f"[sync] git.nixosRepo: '{current}' → '{detected}'")

    # git.name / git.email — GitHub API로 자동 감지, 실패 시 대화형 폴백
    owner = detected.split("/")[0]
    git_sec   = base.get("git", {})
    cur_name  = git_sec.get("name", "")
    cur_email = git_sec.get("email", "")

    gh = _fetch_github_user(owner)
    if gh:
        if gh["name"] and gh["name"] != cur_name:
            _update_field(base_path, r'(name\s*=\s*")[^"]*(")', gh["name"])
            print(f"[sync] git.name: '{cur_name}' → '{gh['name']}'")
        if gh["email"] and gh["email"] != cur_email:
            _update_field(base_path, r'(email\s*=\s*")[^"]*(")', gh["email"])
            print(f"[sync] git.email: '{cur_email}' → '{gh['email']}'")
    else:
        print(f"[sync] GitHub API unavailable. Check: https://github.com/{owner}")
        try:
            new_name = input(f"[sync] git.name [{cur_name}]: ").strip()
            if new_name and new_name != cur_name:
                _update_field(base_path, r'(name\s*=\s*")[^"]*(")', new_name)
                print(f"[sync] git.name: '{cur_name}' → '{new_name}'")
            new_email = input(f"[sync] git.email [{cur_email}]: ").strip()
            if new_email and new_email != cur_email:
                _update_field(base_path, r'(email\s*=\s*")[^"]*(")', new_email)
                print(f"[sync] git.email: '{cur_email}' → '{new_email}'")
        except EOFError:
            pass  # 비대화형 환경 — skip

    # username — 항상 대화형 (시스템 사용자명, GitHub에서 자동 감지 불가)
    cur_username = base.get("username", "")
    try:
        new_username = input(f"[sync] username [{cur_username}]: ").strip()
        if new_username and new_username != cur_username:
            _update_field(base_path, r'(username\s*=\s*")[^"]*(")', new_username)
            print(f"[sync] username: '{cur_username}' → '{new_username}'")
    except EOFError:
        pass  # 비대화형 환경 — skip


def cmd_update_repo(args):
    repo_tmp, new_repo = args[0], args[1]
    toml_path = os.path.join(repo_tmp, "hosts", "_base.toml")
    with open(toml_path, "r") as f:
        content = f.read()
    content = re.sub(
        r'(nixosRepo\s*=\s*")[^"]*(")',
        f'\\g<1>{new_repo}\\g<2>',
        content,
    )
    with open(toml_path, "w") as f:
        f.write(content)


def cmd_username(args):
    repo_tmp = args[0]
    base_path = os.path.join(repo_tmp, "hosts", "_base.toml")
    try:
        with open(base_path, "rb") as f:
            base = tomllib.load(f)
        print(base.get("username", ""))
    except Exception:
        print("")


def cmd_list_hosts(args):
    repo_tmp = args[0]
    hosts_dir = os.path.join(repo_tmp, "hosts")
    entries = []
    for entry in sorted(os.listdir(hosts_dir)):
        # hosts/<hostname>.toml 형식 (평탄 구조)
        if not entry.endswith(".toml") or entry == "_base.toml" or entry.startswith("_preset."):
            continue
        hostname = entry[:-5]  # .toml 제거
        toml_path = os.path.join(hosts_dir, entry)
        with open(toml_path, "rb") as f:
            h = tomllib.load(f)
        entries.append(f"{hostname}|{h.get('type', '?')}|{h.get('preset', '?')}")
    print("\n".join(entries))


def cmd_list_presets(args):
    repo_tmp = args[0]
    hosts_dir = os.path.join(repo_tmp, "hosts")
    names = sorted(
        f[len("_preset."):-len(".toml")]
        for f in os.listdir(hosts_dir)
        if f.startswith("_preset.") and f.endswith(".toml") and f != "_preset.iso.toml"
    )
    print("\n".join(names))


def cmd_disk_labels(args):
    repo_tmp, host = args[0], args[1]
    with open(os.path.join(repo_tmp, "hosts", "_base.toml"), "rb") as f:
        base = tomllib.load(f)
    host_path = os.path.join(repo_tmp, "hosts", f"{host}.toml")
    host_data = {}
    if os.path.exists(host_path):
        with open(host_path, "rb") as f:
            host_data = tomllib.load(f)

    boot_dev = host_data.get("bootDevice", base["bootDevice"])
    disk_dev = host_data.get("diskDevice", base["diskDevice"])

    def extract_label(path):
        prefix = "/dev/disk/by-label/"
        return path[len(prefix):] if path.startswith(prefix) else ""

    print(extract_label(boot_dev), extract_label(disk_dev))


SUBCOMMANDS = {
    "check-repo":   cmd_check_repo,
    "update-repo":  cmd_update_repo,
    "sync-remote":  cmd_sync_remote,
    "username":     cmd_username,
    "list-hosts":   cmd_list_hosts,
    "list-presets": cmd_list_presets,
    "disk-labels":  cmd_disk_labels,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in SUBCOMMANDS:
        print(f"usage: nixstrap.lib-repo.py <subcommand> [args...]", file=sys.stderr)
        print(f"subcommands: {', '.join(SUBCOMMANDS)}", file=sys.stderr)
        sys.exit(1)
    SUBCOMMANDS[sys.argv[1]](sys.argv[2:])
