#!/usr/bin/env python3
"""nixstrap.lib.py — nixstrap.sh용 Python 서브커맨드 헬퍼

서브커맨드:
  check-repo   <repo_tmp>             → base.toml에서 git.nixosRepo 출력
  update-repo  <repo_tmp> <new_repo>  → base.toml의 git.nixosRepo를 in-place 수정
  list-hosts   <repo_tmp>             → hostname|type|preset 형식으로 호스트 목록 출력
  list-presets <repo_tmp>             → 프리셋 이름 출력 (iso 제외)
  free-space   <disk>                 → num:start:end:size 형식으로 빈 공간 출력, 없으면 NONE
  boot-end     <start> <size>         → 부트 파티션 끝 위치 출력
  check-range  <start> <end>          → 유효하면 exit 0, 아니면 exit 1 + stderr 메시지
  disk-labels  <repo_tmp> <host>      → BOOT_LABEL DISK_LABEL 출력 (공백 구분)
  list-parts   <category>             → name|size|fstype|label 형식 (efi/root/disk), 없으면 NONE
"""

import sys
import os
import re
import subprocess
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


def cmd_free_space(args):
    disk = args[0]
    result = subprocess.run(
        ["parted", "-m", disk, "unit", "GiB", "print", "free"],
        capture_output=True,
        text=True,
    )
    blocks = []
    for line in result.stdout.strip().split("\n")[2:]:
        parts = line.rstrip(";").split(":")
        if len(parts) >= 5 and parts[4] == "free":
            start, end, size = parts[1], parts[2], parts[3]
            try:
                size_val = float(re.sub(r"[^0-9.]", "", size))
            except ValueError:
                continue
            if size_val >= 2:
                blocks.append((start, end, size))
    if not blocks:
        print("NONE")
    else:
        for i, (start, end, size) in enumerate(blocks, 1):
            print(f"{i}:{start}:{end}:{size}")


def _parse_to_mib(s):
    s = s.strip()
    val = float(re.sub(r"[^0-9.]", "", s))
    unit = re.sub(r"[0-9. ]", "", s).upper()
    if unit in ("GIB", "G", "GB"):
        return val * 1024
    elif unit in ("MIB", "M", "MB"):
        return val
    return val * 1024  # assume GiB


def cmd_boot_end(args):
    start_mib = _parse_to_mib(args[0])
    size_mib = _parse_to_mib(args[1])
    end_mib = start_mib + size_mib
    if end_mib >= 1024 and end_mib % 1024 == 0:
        print(f"{int(end_mib // 1024)}GiB")
    else:
        print(f"{end_mib:.0f}MiB")


def cmd_check_range(args):
    start_str, end_str = args[0], args[1]
    try:
        start_mib = _parse_to_mib(start_str)
        end_mib = _parse_to_mib(end_str)
    except Exception as e:
        print(f"cannot parse range: {e}", file=sys.stderr)
        sys.exit(1)
    if end_mib <= start_mib:
        print(f"end ({end_str}) must be greater than start ({start_str})", file=sys.stderr)
        sys.exit(1)
    size_gib = (end_mib - start_mib) / 1024
    if size_gib < 5:
        print(f"range too small ({size_gib:.1f}GiB); need at least 5GiB", file=sys.stderr)
        sys.exit(1)


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


def cmd_list_parts(args):
    import json

    category = args[0]  # efi, root, disk
    result = subprocess.run(
        ["lsblk", "-J", "-o", "NAME,SIZE,TYPE,FSTYPE,LABEL"],
        capture_output=True,
        text=True,
    )
    devices = json.loads(result.stdout).get("blockdevices", [])

    # 디스크와 그 하위 파티션을 flat 리스트로 수집
    entries = []
    for dev in devices:
        if category == "disk" and dev.get("type") == "disk":
            name = dev["name"]
            # loop, zram, rom 등 제외
            if any(name.startswith(p) for p in ("loop", "zram", "sr")):
                continue
            entries.append(f"{name}|{dev.get('size', '?')}")
            continue
        for child in dev.get("children", []):
            if child.get("type") != "part":
                continue
            fs = child.get("fstype") or ""
            label = child.get("label") or ""
            size = child.get("size", "?")
            name = child["name"]
            if category == "efi" and fs == "vfat":
                entries.append(f"{name}|{size}|{fs}|{label}")
            elif category == "root" and fs in ("btrfs", "ext4", "xfs", "f2fs"):
                entries.append(f"{name}|{size}|{fs}|{label}")

    if not entries:
        print("NONE")
    else:
        print("\n".join(entries))


SUBCOMMANDS = {
    "check-repo":   cmd_check_repo,
    "update-repo":  cmd_update_repo,
    "list-hosts":   cmd_list_hosts,
    "list-presets": cmd_list_presets,
    "free-space":   cmd_free_space,
    "boot-end":     cmd_boot_end,
    "check-range":  cmd_check_range,
    "disk-labels":  cmd_disk_labels,
    "list-parts":   cmd_list_parts,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in SUBCOMMANDS:
        print(f"usage: nixstrap.lib.py <subcommand> [args...]", file=sys.stderr)
        print(f"subcommands: {', '.join(SUBCOMMANDS)}", file=sys.stderr)
        sys.exit(1)
    SUBCOMMANDS[sys.argv[1]](sys.argv[2:])
