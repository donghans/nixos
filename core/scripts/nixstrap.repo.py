#!/usr/bin/env python3
"""nixstrap.repo.py — nixstrap.sh용 레포지토리/설정 서브커맨드 헬퍼

서브커맨드:
  check-repo   <repo_tmp>             → base.toml에서 git.nixosRepo 출력
  update-repo  <repo_tmp> <new_repo>  → base.toml의 git.nixosRepo를 in-place 수정
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
    base_path = os.path.join(repo_tmp, "hosts", "base.toml")
    try:
        with open(base_path, "rb") as f:
            base = tomllib.load(f)
        print(base.get("git", {}).get("nixosRepo", ""))
    except Exception:
        print("")


def cmd_update_repo(args):
    repo_tmp, new_repo = args[0], args[1]
    toml_path = os.path.join(repo_tmp, "hosts", "base.toml")
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
    base_path = os.path.join(repo_tmp, "hosts", "base.toml")
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
        toml_path = os.path.join(hosts_dir, entry, "host.toml")
        if not os.path.isfile(toml_path):
            continue
        with open(toml_path, "rb") as f:
            h = tomllib.load(f)
        entries.append(f"{entry}|{h.get('type', '?')}|{h.get('preset', '?')}")
    print("\n".join(entries))


def cmd_list_presets(args):
    repo_tmp = args[0]
    preset_dir = os.path.join(repo_tmp, "mods", "_preset")
    names = sorted(
        f[:-5]
        for f in os.listdir(preset_dir)
        if f.endswith(".toml") and f != "iso.toml"
    )
    print("\n".join(names))


def cmd_disk_labels(args):
    repo_tmp, host = args[0], args[1]
    with open(os.path.join(repo_tmp, "hosts", "base.toml"), "rb") as f:
        base = tomllib.load(f)
    host_path = os.path.join(repo_tmp, "hosts", host, "host.toml")
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
    "username":     cmd_username,
    "list-hosts":   cmd_list_hosts,
    "list-presets": cmd_list_presets,
    "disk-labels":  cmd_disk_labels,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in SUBCOMMANDS:
        print(f"usage: nixstrap.repo.py <subcommand> [args...]", file=sys.stderr)
        print(f"subcommands: {', '.join(SUBCOMMANDS)}", file=sys.stderr)
        sys.exit(1)
    SUBCOMMANDS[sys.argv[1]](sys.argv[2:])
