# 📦 Mods 등록 · 삭제 가이드

Mods 프레임워크에서 새 기능을 추가하거나 기존 기능을 제거하는 방법을 단계별로 설명합니다.

---

## 기본 개념

### 파일 위치와 자동 탐색

`core/lib/mods-lib.nix`의 `recursiveImportDir`이 `mods/` 하위를 재귀 탐색하여 `.nix` 파일을 자동으로 모듈로 로드합니다. 아래 파일은 자동 제외됩니다.

- `_`로 시작하는 디렉터리·파일 (`_data/`, `_lib.nix` 등)
- `*.home.nix`, `*.overlay.nix`
- `default.nix`

즉, **`mods/<domain>/` 아래에 `.nix` 파일을 생성하면 자동으로 모듈로 로드됩니다.** 별도 등록 코드가 필요 없습니다.

### Mod 헬퍼 패턴

| 헬퍼 | 역할 | enable 옵션 |
|------|------|-------------|
| `mkMod __curPos "설명"` | 독립 기능 단위 | 자동 생성 (`mods.<path>.enable`) |
| `mkModOf "parent.path" __curPos "설명"` | 부모 활성화 시 기본 켜지는 자식 | 자동 생성, 부모 enable 시 `mkDefault true` |
| `mkPartOf "parent.path"` | 자체 enable 없이 부모에 귀속 | 없음 (부모 enable만 따름) |

---

## 새 Mod 추가하기

### 1단계: `.nix` 파일 생성

```nix
# mods/sys/services/my-service.nix
{mkMod, ...}:
mkMod __curPos "My service description" ({cfg, pkgs, lib, ...}: {
  # os = NixOS 시스템 설정 (nixosConfigurations에만 적용)
  os = {
    services.my-service.enable = true;
  };
  # hm = Home Manager 설정 (homeConfigurations에만 적용)
  hm = {
    home.packages = [pkgs.my-package];
  };
})
```

#### 부모 도메인에 연결하는 자식 모듈인 경우

```nix
# mods/gui/base/my-feature.nix
{mkModOf, ...}:
mkModOf "mods.gui" __curPos "My GUI feature" ({cfg, pkgs, ...}: {
  hm = {
    programs.my-app.enable = true;
  };
})
```

`mods.gui.enable = true`이면 자동으로 `mods.gui.base.my-feature.enable = true` (mkDefault)가 됩니다.

#### 자체 enable 없이 부모에 귀속되는 경우

```nix
# mods/gui/base/sub-part.nix
{mkPartOf, ...}:
mkPartOf "mods.gui.base.my-feature" ({cfg, pkgs, ...}: {
  hm = {
    home.file.".config/my-app/config".text = "...";
  };
})
```

### 2단계: 프리셋에 등록 (`mkMod`/`mkModOf`만 해당)

`mkMod` 또는 `mkModOf`를 사용하면 고유한 `enable` 옵션이 생성됩니다. 이 옵션을 모든 관련 프리셋 TOML에 등록해야 합니다.

**등록하지 않으면 `nixup check` 실행 시 Coverage Check 오류가 발생합니다.**

```toml
# hosts/_preset.workstation.toml
[mods.sys.services]
my-service = false   # 기본 비활성화
```

```toml
# hosts/_preset.server.toml
[mods.sys.services]
my-service = true    # 서버에서는 기본 활성화
```

> **모든 프리셋에 등록해야 합니다** (`_preset.workstation.toml`, `_preset.server.toml`, `_preset.iso.toml` 모두). 누락된 프리셋이 있으면 Coverage Check 오류가 발생합니다.

#### 예외: 의도적으로 프리셋 밖에서 관리

특정 옵션을 프리셋에서 명시적으로 제외하고 싶다면 `[explicitOptional]`에 등록합니다.

```toml
# hosts/_preset.workstation.toml
[explicitOptional]
paths = [
  "mods.sys.services.my-internal-feature.enable",
]
```

### 3단계: 검증

```bash
nixup check
```

Coverage Check가 통과하면 설정이 올바르게 등록된 것입니다.

---

## Mod 삭제하기

### 1단계: `.nix` 파일 삭제

```bash
rm mods/sys/services/my-service.nix
```

> `_data/` 안에 관련 데이터 파일이 있다면 함께 삭제하세요.

### 2단계: 프리셋 TOML에서 항목 제거

모든 `hosts/_preset.*.toml` 파일에서 해당 옵션 줄을 제거합니다.

```toml
# 제거 전
[mods.sys.services]
my-service = false
docker = true

# 제거 후
[mods.sys.services]
docker = true
```

> `[explicitOptional]`에 등록된 항목이 있다면 거기서도 제거하세요.

### 3단계: 각 호스트 TOML 확인

`hosts/<hostname>.toml`에서 해당 mod를 명시적으로 오버라이드하고 있다면 제거합니다.

### 4단계: 검증

```bash
nixup check
```

---

## Coverage Check 오류 대응

`nixup check` 실행 시 Coverage Check 오류가 나타나면:

### 오류 1: "프리셋에 등록되지 않은 모드 옵션"

```
[Mods Coverage] 프리셋에 등록되지 않은 모드 옵션이 있습니다.
  누락된 옵션: mods.sys.services.my-service.enable
```

→ `hosts/_preset.*.toml`의 해당 섹션에 `my-service = false`(또는 `true`) 추가

### 오류 2: "같은 그룹에서 일부 옵션만 프리셋에 명시"

```
[Mods Coverage] 같은 그룹에서 일부 옵션만 프리셋에 명시되었습니다.
  불완전한 그룹: mods.sys.services: 누락 → mods.sys.services.my-service.enable
```

→ `[mods.sys.services]` 섹션에 이미 다른 항목이 있는데 새 항목을 추가하지 않은 경우. 같은 섹션의 나머지 항목도 모두 기재

---

## 비-Nix 데이터 파일 (`mods/_data/`)

셸 스크립트, CSS, XML, PS1 등 `.nix`가 아닌 파일은 `mods/_data/`에 두고 `builtins.readFile`로 읽습니다.

```nix
# mods/sys/base/zsh.nix에서 사용 예
initContent = builtins.readFile ../../_data/zsh/init.zsh;
```

`mods/_data/`는 `recursiveImportDir`의 자동 탐색에서 제외되므로 `.nix` 파일이 있어도 모듈로 로드되지 않습니다.
