# Disk Tools Integration Plan (Draft for Later)

## Background & Motivation

디스크 공간 부족 시 원인 추적을 위한 CLI 도구 모음. Netdata(monitoring-refactor 계획)가 디스크 사용량 개요를 커버하므로, `duf` 같은 개요성 도구는 제외하고 **디렉터리 단위 드릴다운**에 집중한다.

## 범위

- **포함**: `dust` (디렉터리별 용량 시각화), `ncdu` (인터랙티브 탐색), `dsize`/`dtop` alias
- **제외**: `duf`, `dfx`, `dutotal`, `du1` — Netdata 또는 `df` 기본 명령으로 충분

## Key Files & Context

- **`mods/sys/utils/disk-tools.nix`** (New File): 패키지 정의 및 alias
- **`mods/sys/default.nix`** (Modified File): 새 모듈 import 추가
- **`mods/_preset/workstation.toml`** (Modified File): workstation 프리셋에서 활성화

## Implementation Steps (For Later)

### 1. Create `mods/sys/utils/disk-tools.nix`

```nix
{
  config,
  lib,
  pkgs,
  forOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.utils.disk-tools;

  aliases = {
    dsize = "du -sh * | sort -h";
    dtop = "du -ah . | sort -rh | head -n 10";
  };
in {
  options.mods.sys.utils.disk-tools.enable = mkEnableOption "Disk drill-down tools (dust, ncdu)";

  config = mkIf cfg.enable (
    if forOS
    then {
      environment.systemPackages = with pkgs; [ du-dust ncdu ];
      environment.shellAliases = aliases;
    }
    else {
      home.packages = with pkgs; [ du-dust ncdu ];
      home.shellAliases = aliases;
    }
  );
}
```

### 2. Import the module in `mods/sys/default.nix`

```nix
  imports =
    [
      ./fonts.nix
      ./vfs.nix
      ./utils/nfd.nix
      ./utils/disk-tools.nix
      ./services/bluetooth.nix
      ...
```

### 3. Enable in `mods/_preset/workstation.toml`

```toml
[mods.sys.utils]
nfd = true
disk-tools = true
```

## Verification & Testing (For Later)

1. `nixup check` — 문법 검사 및 flake 평가 확인
2. `nixup os` — 변경 적용
3. 새 셸에서 수동 확인:
   - `dust` 실행
   - `ncdu .` 실행
   - `dsize`, `dtop` alias 동작 확인
