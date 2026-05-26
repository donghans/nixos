#!/usr/bin/env python3
# core/scripts/nixup.task-resolve.py
# TOML 소스 파일 → resolved.json + presets.json (OUT_DIR 루트에 생성)
#
# 사용법:
#   python3 nixup.task-resolve.py              # NIXOS_PATH 기준 읽기/쓰기 (레거시)
#   python3 nixup.task-resolve.py /tmp/dir     # 지정 디렉토리 기준 읽기/쓰기 (task-check.sh 등)
#   python3 nixup.task-resolve.py /src /out    # /src에서 읽고 /out에 생성 (nixup 내부 호출)
#
# 생성 파일:
#   resolved.json  — 호스트별 merged 데이터 (flake.nix, lib-build.sh 사용)
#   presets.json   — 프리셋별 전체 mods 맵 + explicitOptional (flake.nix 사용)

import json
import os
import sys
import tomllib


def detect_ram_gb():
    """물리 RAM 크기를 /proc/meminfo에서 읽어 GB 단위로 반환 (ceil)."""
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    kb = int(line.split()[1])
                    return (kb + 1048575) // 1048576  # ceil to GB
    except Exception:
        pass
    return None

script_dir = os.path.dirname(os.path.abspath(__file__))
src_path = os.path.normpath(os.path.join(script_dir, "../.."))
if len(sys.argv) == 3:
    src_path = os.path.abspath(sys.argv[1])
    target_path = os.path.abspath(sys.argv[2])
elif len(sys.argv) == 2:
    src_path = os.path.abspath(sys.argv[1])
    target_path = src_path
else:
    target_path = src_path


def write_json(path, data):
    open(path, "w").write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


# == presets.json 생성 ==
# hosts/_preset.*.toml → presets.json (Nix가 읽는 JSON 형식)
hosts_dir = f"{src_path}/hosts"
all_presets = {}

for entry in sorted(os.listdir(hosts_dir)):
    if not entry.startswith("_preset.") or not entry.endswith(".toml"):
        continue
    preset_name = entry[len("_preset."):-len(".toml")]
    with open(os.path.join(hosts_dir, entry), "rb") as f:
        preset_data = tomllib.load(f)

    # stateVersion 미지정 → None (rolling)
    state_version = preset_data.get("stateVersion", None)
    all_presets[preset_name] = {
        "stateVersion": state_version,
        "mods": preset_data.get("mods", {}),
        "explicitOptional": preset_data.get("explicitOptional", {}).get("paths", []),
    }
    print(f"preset:{preset_name}  stateVersion={state_version}")

presets_path = os.path.join(target_path, "presets.json")
write_json(presets_path, all_presets)
print(f"→ {presets_path}")

# == resolved.json 생성 ==
# hosts/base.toml + hosts/<hostname>.toml + preset → resolved.json
with open(f"{src_path}/hosts/_base.toml", "rb") as f:
    base = tomllib.load(f)

rolling_state_version = base["rollingStateVersion"]

hosts_dir = f"{src_path}/hosts"
all_resolved = {}

for entry in sorted(os.listdir(hosts_dir)):
    # hosts/<hostname>.toml 형식 (평탄 구조)
    if not entry.endswith(".toml") or entry == "_base.toml" or entry.startswith("_preset."):
        continue
    hostname = entry[:-5]  # .toml 제거
    host_toml_path = os.path.join(hosts_dir, entry)

    with open(host_toml_path, "rb") as f:
        host = tomllib.load(f)

    if "type" not in host:
        print(f"Error: '{host_toml_path}' 에 'type' 필드가 없습니다.", file=sys.stderr)
        print(f"       가능한 값: desktop, laptop, server, rpi", file=sys.stderr)
        sys.exit(1)
    if "preset" not in host:
        print(f"Error: '{host_toml_path}' 에 'preset' 필드가 없습니다.", file=sys.stderr)
        print(f"       사용 가능한 프리셋: {', '.join(sorted(all_presets.keys()))}", file=sys.stderr)
        sys.exit(1)
    preset_name = host["preset"]
    if preset_name not in all_presets:
        print(f"Error: '{host_toml_path}' 의 preset='{preset_name}' 이 존재하지 않습니다.", file=sys.stderr)
        print(f"       사용 가능한 프리셋: {', '.join(sorted(all_presets.keys()))}", file=sys.stderr)
        sys.exit(1)
    preset = all_presets[preset_name]

    # stateVersion: host.toml 명시 > preset.stateVersion > base.toml rollingStateVersion
    state_version = host.get("stateVersion", preset["stateVersion"]) or rolling_state_version
    is_rolling = host.get("stateVersion") is None and preset["stateVersion"] is None

    # mods: host.toml 오버라이드만 (프리셋 mods는 flake.nix가 presets.json에서 병합)
    mods = {}
    for k, v in host.get("mods", {}).items():
        mods[k] = v

    # ramGb: host.toml 명시 우선 → 없으면 /proc/meminfo 자동 감지 (관리 머신 기준)
    # 원격 호스트는 nixstrap/rnixstrap이 설치 시점에 host.toml에 기재함
    ram_gb = host.get("ramGb") or detect_ram_gb()

    deploy_section = host.get("deploy", None)
    if deploy_section and "sshKey" in deploy_section:
        deploy_section = dict(deploy_section)
        deploy_section["sshKey"] = os.path.expanduser(deploy_section["sshKey"])

    all_resolved[hostname] = {
        "hostname": hostname,
        "system": host.get("system", base["system"]),
        "type": host["type"],
        "ramGb": ram_gb,
        "swapGb": host.get("swapGb"),       # None → Nix 기본값 적용 (ceil(ramGb*0.75))
        "tmpfsSize": host.get("tmpfsSize"),  # None → Nix 기본값 적용 ("100%")
        "zramPercent": host.get("zramPercent"),  # None → Nix 기본값 적용 (50)
        "bootLoader": host.get("bootLoader", "systemd-boot"),
        "deploy": deploy_section,            # None → 로컬 호스트 (배포 대상 아님)
        "diskDevice":    host.get("diskDevice",    base["diskDevice"]),
        "bootDevice":    host.get("bootDevice",    base["bootDevice"]),
        "timeZone":      host.get("timeZone",      base["timeZone"]),
        "defaultLocale": host.get("defaultLocale", base["defaultLocale"]),
        "extraLocale":   host.get("extraLocale",   base.get("extraLocale")),  # None → null
        "nixCacheAddr":  host.get("nixCacheAddr",  base.get("nixCacheAddr", "")),
        "preset": preset_name,
        "username": host.get("username", base["username"]),
        "git": {**base.get("git", {}), **host.get("git", {})},
        "stateVersion": state_version,       # 항상 non-null (rolling 시 rollingStateVersion 폴백)
        "rollingStateVersion": rolling_state_version,
        "isRolling": is_rolling,
        "mods": mods,
        "preauthKeys": host.get("preauth-keys", []),
    }
    print(f"{hostname}  stateVersion={state_version}  isRolling={is_rolling}")

resolved_path = os.path.join(target_path, "resolved.json")
write_json(resolved_path, all_resolved)
print(f"→ {resolved_path}")
