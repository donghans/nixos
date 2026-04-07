#!/usr/bin/env python3
# core/scripts/nhw.resolve.py
# TOML 소스 파일 → resolved.json + presets.json (TARGET_DIR 루트에 생성)
#
# 사용법:
#   python3 nhw.resolve.py              # NIXOS_PATH 기준 (nhw 내부 호출)
#   python3 nhw.resolve.py /tmp/dir     # 지정 디렉토리 기준 (task-check.sh 등)
#
# 생성 파일:
#   resolved.json  — 호스트별 merged 데이터 (flake.nix, nhw.lib-build.sh 사용)
#   presets.json   — 프리셋별 전체 mods 맵 + explicitOptional (flake.nix 사용)

import json
import os
import sys
import tomllib

script_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.normpath(os.path.join(script_dir, "../.."))
target_path = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else src_path


def write_json(path, data):
    open(path, "w").write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


# == presets.json 생성 ==
# mods/_preset/*.toml → presets.json (Nix가 읽는 JSON 형식)
presets_dir = f"{target_path}/mods/_preset"
all_presets = {}

for entry in sorted(os.listdir(presets_dir)):
    if not entry.endswith(".toml"):
        continue
    preset_name = entry[:-5]  # .toml 제거
    with open(os.path.join(presets_dir, entry), "rb") as f:
        preset_data = tomllib.load(f)

    # stateVersion 미지정 → None (rolling)
    state_version = preset_data.get("stateVersion", None)
    all_presets[preset_name] = {
        "stateVersion": state_version,
        "mods": preset_data.get("mods", {}),
        "explicitOptional": preset_data.get("explicitOptional", {}).get("paths", []),
    }
    print(f"[resolve] preset:{preset_name}  stateVersion={state_version}")

presets_path = os.path.join(target_path, "presets.json")
write_json(presets_path, all_presets)
print(f"[resolve] → {presets_path}")

# == resolved.json 생성 ==
# hosts/base.toml + hosts/<hostname>/host.toml + preset → resolved.json
with open(f"{target_path}/hosts/base.toml", "rb") as f:
    base = tomllib.load(f)

hosts_dir = f"{target_path}/hosts"
all_resolved = {}

for entry in sorted(os.listdir(hosts_dir)):
    host_dir = os.path.join(hosts_dir, entry)
    host_toml_path = os.path.join(host_dir, "host.toml")
    if not os.path.isdir(host_dir) or not os.path.exists(host_toml_path):
        continue

    with open(host_toml_path, "rb") as f:
        host = tomllib.load(f)

    preset_name = host["preset"]
    preset = all_presets[preset_name]

    # stateVersion: host.toml 명시 > preset.stateVersion > None (rolling)
    state_version = host.get("stateVersion", preset["stateVersion"])
    is_rolling = state_version is None

    # mods: host.toml 오버라이드만 (프리셋 mods는 flake.nix가 presets.json에서 병합)
    mods = {}
    for k, v in host.get("mods", {}).items():
        mods[k] = v

    all_resolved[entry] = {
        "hostname": entry,
        "system": host.get("system", base["system"]),
        "isLaptop": host["isLaptop"],
        "ramGb": host.get("ramGb"),
        "preset": preset_name,
        "username": base["username"],
        "git": base["git"],
        "stateVersion": state_version,
        "isRolling": is_rolling,
        "mods": mods,
    }
    print(f"[resolve] {entry}  stateVersion={state_version}  isRolling={is_rolling}")

resolved_path = os.path.join(target_path, "resolved.json")
write_json(resolved_path, all_resolved)
print(f"[resolve] → {resolved_path}")
