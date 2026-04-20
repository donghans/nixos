# mods mkMod 마이그레이션 계획

## 완료된 기반 작업

- `mods/_lib.nix` — `mkMod` 헬퍼 구현 완료
- `mods/_template.nix` — 신규 모듈 작성 템플릿 생성
- `core/lib/builders.nix` — `mkMod`를 `specialArgs`로 전 모듈에 주입 완료

이후 모든 `.nix` 모듈에서 `{ mkMod, ... }:` 로 바로 사용 가능.

---

## 분류 기준

| 분류 | 설명 | 마이그레이션 난이도 |
|------|------|-----------------|
| **Simple** | `isNixOS` 분기 + `mkIf cfg.enable` 패턴만 사용 | 낮음 |
| **HomeOnly** | HM 설정만 있음 (`os` 생략) | 낮음 |
| **OSOnly** | OS 설정만 있음 (`hm` 생략) | 낮음 |
| **MkMerge** | `lib.mkMerge` 사용 — `_type` 감지로 그대로 통과 | 낮음~중간 |
| **Complex** | `mkDefault`, `mkBefore`, `mkForce`, 중첩 조건, 커스텀 스크립트 | 중간~높음 |
| **NoEnable** | enable 없는 항상-켜지는 하위 설정 파일 | 별도 판단 |

---

## Phase 1 — Simple / HomeOnly / OSOnly (27개)

`mkMod` 적용이 가장 직관적인 파일들. 기계적 치환 가능.

**변환 패턴 (Simple):**
```nix
# Before
{ config, lib, pkgs, isNixOS ? false, ... }:
with lib;
let cfg = config.mods.sys.services.docker;
in {
  options.mods.sys.services.docker = {
    enable = mkEnableOption "Docker";
  };
  config = if isNixOS then mkIf cfg.enable {
    virtualisation.docker.enable = true;
  } else {};
}

# After
{ mkMod, pkgs, ... }:
mkMod "mods.sys.services.docker" "Docker" ({ cfg, ... }: {
  os = { virtualisation.docker.enable = true; };
})
```

### Simple (21개)

| 파일 | 특이사항 |
|------|--------|
| `sys/fonts.nix` | |
| `sys/vfs.nix` | |
| `sys/utils/nfd.nix` | |
| `sys/services/cockpit.nix` | |
| `sys/services/docker.nix` | |
| `sys/services/frp.nix` | |
| `sys/services/caddy.nix` | `extraConfig` 옵션 포함 |
| `sys/services/headscale.nix` | |
| `sys/services/incus.nix` | |
| `sys/services/incus-guest.nix` | |
| `sys/services/tailscale.nix` | `mkOrder` 사용 → `_type` 감지로 자동 통과 |
| `sys/base/home/zsh.nix` | enable 없음 → `desc = null` |
| `gui/core/home/fuzzel.nix` | enable 없음 → `desc = null` |
| `gui/core/home/hyprlock.nix` | enable 없음 → `desc = null` |
| `gui/core/home/hyprpaper.nix` | enable 없음 → `desc = null` |
| `gui/core/home/kitty.nix` | enable 없음 → `desc = null` |
| `gui/core/home/mako.nix` | enable 없음 → `desc = null` |
| `gui/core/home/satty.nix` | enable 없음 → `desc = null` |
| `gui/core/home/waybar.nix` | enable 없음 → `desc = null` |
| `devel/base/home.nix` | 빈 모듈 — 파일 제거 검토 |
| `devel/base/os.nix` | 빈 모듈 — 파일 제거 검토 |

### HomeOnly (5개)

`os` 블록 생략. 나머지는 Simple과 동일.

| 파일 |
|------|
| `gui/apps/vivaldi.nix` |
| `gui/apps/slack.nix` |
| `gui/apps/bitwarden.nix` |
| `gui/apps/speedcrunch.nix` |
| `devel/apps/zed.nix` |

### OSOnly (1개)

`hm` 블록 생략.

| 파일 |
|------|
| `devel/toolchains/jetbrains-android-studio.extra.nix` |

---

## Phase 2 — MkMerge (6개)

`lib.mkMerge`를 `os` / `hm` 값으로 직접 작성. `_type` 감지로 자동 통과되므로 구조만 맞추면 됨.

**변환 패턴:**
```nix
# After
{ mkMod, lib, ... }:
mkMod "mods.sys.services.nix-cache-proxy" "Nix binary cache proxy" ({ cfg, config, lib, ... }: {
  options = {
    port       = lib.mkOption { type = lib.types.port; default = 7070; ... };
    maxSize    = lib.mkOption { ... };
    inactiveDays = lib.mkOption { ... };
  };
  os = lib.mkMerge [
    (lib.mkIf cfg.enable { services.nginx = { ... }; })
    (lib.mkIf hasProxy { nix.settings = { ... }; })
  ];
})
```

| 파일 | 특이사항 |
|------|--------|
| `sys/services/nix-cache-proxy.nix` | 서버 모드 + 클라이언트 모드 분기 |
| `gui/core/xdg.nix` | `optionalAttrs` 병합 |
| `gui/core/polkit.nix` | `optionalAttrs` 병합 |
| `gui/core/fcitx.nix` | `optionalAttrs` 병합 |
| `gui/core/home.nix` | OS/HM 혼재 없음, HM mkMerge만 |
| `gui/utils/custom-notify-logger.nix` | systemd 서비스 + 로그 디렉터리 분기 |

---

## Phase 3 — Complex (14개)

`mkMod`로 `cfg` 자동 해결 + `isNixOS` 제거는 동일하게 적용. 내부 로직은 직접 작성.
파일별로 읽고 판단 필요.

| 파일 | 복잡도 요인 |
|------|-----------|
| `sys/base/os.nix` | 다수 하위 `_*.nix` import, `mkDefault` 사용 |
| `sys/base/home.nix` | `mkDefault` + home 공통 설정 |
| `sys/services/bluetooth.nix` | 중첩 `mkIf` |
| `sys/services/networkmanager.nix` | 중첩 `mkIf` |
| `sys/services/incus-win11.nix` | XML 인라인, PowerShell, 복잡한 VM 설정 |
| `gui/core/os.nix` | 다수 서비스 통합 설정 |
| `gui/core/greeter.nix` | systemd 서비스 커스터마이징 |
| `gui/core/home/wl-clip.nix` | 커스텀 스크립트 + systemd |
| `devel/toolchains/node.nix` | `mkDefault` + overlay 연동 |
| `devel/toolchains/python.nix` | `mkDefault` |
| `devel/toolchains/fvm.nix` | `mkDefault` + overlay 연동 |
| `devel/toolchains/devbox.nix` | `mkDefault` + 템플릿 파일 |
| `devel/toolchains/jetbrains.nix` | `map` + `mkDefault` + overlay 연동 |
| `devel/apps/llm-cli.nix` | `overrideAttrs` + 패치 로직 |

> **참고**: Complex 파일들은 `mkMod` 적용 시 `cfg` 자동 해결과 `isNixOS` 제거가 주된 이득.
> 내부 `mkMerge`/`mkDefault`/커스텀 로직은 `os`/`hm` 블록 안에 그대로 유지.

---

## Phase 4 — 선택적 정리

### `isNixOS` → `forOS` 이름 변경

`mkMod`를 사용하는 새 모듈에는 `isNixOS`가 노출되지 않으므로 우선순위 낮음.
마이그레이션 완료 후 `builders.nix`의 `specialArgs` 키 이름을 변경하고,
`mkMod` 내부의 `isNixOS ? false` 바인딩도 함께 수정.

### 빈 모듈 제거

`devel/base/home.nix`, `devel/base/os.nix` — 내용이 없으면 import 라인도 함께 제거.

---

## 마이그레이션 순서 제안

```
Phase 1 Simple/HomeOnly/OSOnly (27개)
  → 기계적 치환, 먼저 완료 후 nixup check로 검증

Phase 2 MkMerge (6개)
  → mkMerge 구조 유지하며 os/hm 블록으로 감싸기

Phase 3 Complex (14개)
  → 파일별 개별 작업, 검증 병행

Phase 4 (선택)
  → isNixOS rename, 빈 파일 제거
```

## 검증

각 Phase 완료 후:
```bash
nixup check   # shellcheck, statix, deadnix, 빌드 검증
nixup os --build   # 실제 빌드 통과 확인
```
