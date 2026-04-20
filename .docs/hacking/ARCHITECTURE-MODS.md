# 🔧 Mods 프레임워크 — 내부 작동 원리

> **다이어그램**: [ARCHITECTURE-MODS.mermaid](./ARCHITECTURE-MODS.mermaid)
> **사용법 및 API**: [MODS.md](../manual/MODS.md)

이 문서는 Mods 프레임워크의 내부 메커니즘을 설명합니다. 파일을 모듈로 로드하고, 옵션을 자동 생성하고, 조건부로 적용하는 전체 파이프라인입니다.

---

## 1. 모듈 자동 스캐닝 (`recursiveImportDir`)

**핵심 파일**: `core/lib/mods.nix`

`host.nix`가 `recursiveImportDir ../../mods`를 호출하면, `mods/` 하위의 모든 `.nix` 파일을 재귀적으로 탐색합니다. **동일한 모듈 집합이 NixOS와 Home Manager 양쪽에 로드됩니다** (host.nix에서 NixOS modules와 HM sharedModules에 각각 주입).

### 제외 규칙

| 패턴 | 이유 |
|------|------|
| `_` prefix 디렉터리 | `_data/`(비-Nix 데이터), `_preset/`(제거됨) 등 모듈이 아닌 디렉터리 |
| `_` prefix 파일 | `_template.nix` 등 내부 유틸 |
| `*.home.nix` | 호스트별 조건부 로드 파일 — `host.nix`에서 별도 처리 |
| `*.overlay.nix` | 오버레이 전용 — `flake.outputs.nix`가 별도로 수집하여 `customOverlays`에 등록 |
| `default.nix` | Nix 모듈 시스템이 디렉터리 import 시 `default.nix`를 자동 로드하므로 중복 방지 |

### 탐색 예시

```
mods/
├── sys/
│   ├── services/
│   │   ├── docker.nix       ← 로드됨
│   │   └── incus.nix        ← 로드됨
│   └── base/
│       ├── core.nix          ← 로드됨
│       └── zsh.nix           ← 로드됨
├── gui/
│   ├── base/
│   │   ├── core.nix          ← 로드됨
│   │   └── waybar.nix        ← 로드됨
│   └── apps/
│       └── vivaldi.nix       ← 로드됨
├── _data/                     ← 전체 제외 (_ prefix)
│   └── zsh/init.zsh
└── _template.nix              ← 제외 (_ prefix)
```

---

## 2. 경로 자동 유도 (`pathFromPos`)

`mkMod __curPos "desc" bodyFn`에서 `__curPos`는 Nix 내장 변수로, 호출 시점의 파일 위치를 담고 있습니다.

### 변환 과정

```
__curPos.file = "/home/user/nixos/mods/gui/apps/vivaldi.nix"
     ↓ modsRoot("/home/user/nixos/mods") 기준 상대 경로
"gui/apps/vivaldi.nix"
     ↓ .nix 제거
"gui/apps/vivaldi"
     ↓ / → . 치환 + "mods." prefix
"mods.gui.apps.vivaldi"
```

이 경로가 NixOS 옵션 트리에서 `options.mods.gui.apps.vivaldi.enable`로 선언됩니다.

### `mkNamedMod`이 필요한 경우

`default.nix`에서는 `__curPos.file`이 `mods/gui/default.nix`가 되어 경로가 `mods.gui.default`로 잘못 변환됩니다. 이때 `mkNamedMod "mods.gui" "desc" bodyFn`으로 경로를 직접 지정합니다.

---

## 3. 헬퍼 패턴 — 왜 3가지인가

### 비교

| | `mkMod` | `mkModOf` | `mkPartOf` |
|---|---|---|---|
| **enable 옵션** | 자동 생성 | 자동 생성 | 없음 |
| **활성화 조건** | preset/host.toml에서 명시 | 부모 enable 시 `mkDefault true` | 부모 enable에 종속 |
| **cfg 바인딩** | 자기 경로의 config | 자기 경로의 config | **부모** 경로의 config |
| **preset TOML 등록** | 필요 | 필요 | 불필요 |
| **Coverage Check 대상** | 예 | 예 | 아니오 |

### 선택 기준

```
사용자가 직접 끄고 켤 수 있어야 하는가?
├── 아니오 → mkPartOf (부모와 항상 같이)
└── 예
    ├── 부모 도메인 활성화 시 기본 켜짐? → mkModOf
    └── 완전히 독립? → mkMod
```

**`mkMod`**: 서비스(docker, bluetooth), 도메인 마스터 스위치(gui.nix, devel.nix)
**`mkModOf`**: GUI 앱(vivaldi, slack), 개발 도구(node, python) — 부모 도메인에 기본 포함
**`mkPartOf`**: 설정 파편(키바인딩, 테마, 커서) — 옵션으로 노출할 필요 없는 서브파트

---

## 4. Enable 계층 구조

3단계 계층으로 구성됩니다.

### 4-1. 마스터 스위치

```nix
# mods/gui.nix
{lib, config, ...}: {
  options.mods.gui.enable = lib.mkEnableOption "GUI Bundle";
  config = lib.mkIf config.mods.gui.enable {
    mods.sys.fonts.enable = true;   # 의존성 자동 활성화
    mods.sys.vfs.enable = true;
  };
}
```

`mods.gui.enable = true`가 되면 fonts, vfs 등 의존성도 함께 켜집니다.

### 4-2. mkModOf cascade

```nix
# mods/gui/apps/vivaldi.nix
mkModOf "mods.gui" __curPos "Vivaldi Browser" ({...}: {hm = {...};})
```

내부적으로 `cascadeModule`이 추가되어:
```nix
config = lib.mkIf config.mods.gui.enable
  (lib.setAttrByPath ["mods" "gui" "apps" "vivaldi"] {enable = lib.mkDefault true;});
```

`mkDefault`이므로 host.toml에서 `vivaldi = false`로 오버라이드 가능합니다.

### 4-3. mkPartOf 종속

```nix
# mods/gui/base/fuzzel.nix
mkPartOf "mods.gui" ({...}: {hm = {...};})
```

자체 enable 없이 `config.mods.gui.enable`에 직접 종속. `lib.mkIf cfg.enable`가 자동 적용됩니다.

### 전체 흐름

```
hosts/_preset.workstation.toml         hosts/<hostname>.toml
        │ [mods.gui]                          │ [mods.gui.apps]
        │ enable = true                       │ vivaldi = false
        ▼                                     ▼
  preset 기본값  ────── recursiveUpdate ────── host 오버라이드
        │
        ▼ modsModule (flake.outputs.nix 주입)
        │
  ┌─────┴──────────────────────────────────────────┐
  │ mods.gui.enable = true        (마스터 스위치)     │
  │   → cascade: vivaldi.enable = mkDefault true    │
  │   → host override: vivaldi.enable = false       │ ← 최종: false
  │   → cascade: core.enable = mkDefault true       │ ← 최종: true
  │   → part: fuzzel (enable 없음, 부모 따름)         │ ← 최종: 활성
  └────────────────────────────────────────────────┘
```

---

## 5. autoWrap — 자동 조건부 적용

`mkMod`/`mkModOf`의 `bodyFn`이 반환하는 `os`/`hm` 블록에 대해:

| 블록 형태 | 처리 |
|-----------|------|
| Plain attrset (`{services.foo = true;}`) | `lib.mkIf cfg.enable` 자동 wrapping |
| `_type` 있음 (`lib.mkMerge [...]`, `lib.mkIf ...`) | **그대로 통과** — 이미 직접 조합한 것 |
| `desc = null` 모듈 | wrapping 건너뜀 (항상 활성화) |

이 덕분에 모듈 작성자가 매번 `lib.mkIf cfg.enable`을 직접 쓸 필요가 없습니다. 복잡한 조건이 필요한 경우에만 `lib.mkMerge`나 `lib.mkIf`를 직접 사용하면 됩니다.

---

## 6. Dual-Context (`isNixOS` 분기)

### 주입 지점

`host.nix`에서:

| 컨텍스트 | 주입 값 | 적용 블록 |
|----------|---------|-----------|
| NixOS system modules | `isNixOS = true` | `body.os` |
| HM sharedModules | `isNixOS = false` | `body.hm` |
| homeConfigurations (standalone) | `isNixOS = false` | `body.hm` |

### 분기 메커니즘

`mkNamedMod` 내부:

```nix
config =
  if isNixOS
  then autoWrap (body.os or {})    # NixOS 평가 시
  else autoWrap (body.hm or {});   # HM 평가 시
```

**모듈 파일 하나에 `os`와 `hm`을 함께 선언**하면, 각 컨텍스트에서 해당 블록만 자동으로 선택됩니다. `os`만 있는 모듈은 HM 평가 시 빈 config를 반환하고, `hm`만 있는 모듈은 NixOS 평가 시 빈 config를 반환합니다.

이 설계 덕분에:
- NixOS 시스템 설정과 사용자 설정을 한 파일에서 관리
- 모듈 작성자가 `isNixOS`를 직접 참조할 필요 없음
- 동일한 모듈 집합을 양쪽에 로드해도 충돌 없음
