#!/usr/bin/env python3
"""nixstrap.lib-part.py — nixstrap.sh용 디스크/파티션 서브커맨드 헬퍼

서브커맨드:
  free-space   <disk>                 → num:start:end:size 형식으로 빈 공간 출력, 없으면 NONE
  boot-end     <start> <size>         → 부트 파티션 끝 위치 출력
  check-range  <start> <end>          → 유효하면 exit 0, 아니면 exit 1 + stderr 메시지
  list-parts   <category>             → name|size|fstype|label 형식 (efi/root/disk), 없으면 NONE
"""

import sys
import os
import re
import subprocess


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
    "free-space":  cmd_free_space,
    "boot-end":    cmd_boot_end,
    "check-range": cmd_check_range,
    "list-parts":  cmd_list_parts,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in SUBCOMMANDS:
        print(f"usage: nixstrap.lib-part.py <subcommand> [args...]", file=sys.stderr)
        print(f"subcommands: {', '.join(SUBCOMMANDS)}", file=sys.stderr)
        sys.exit(1)
    SUBCOMMANDS[sys.argv[1]](sys.argv[2:])
