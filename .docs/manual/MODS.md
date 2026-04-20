# 📦 Mods 사용 가이드

이 프로젝트의 모든 기능은 `mods/` 디렉터리의 모듈(Mod)로 구성됩니다. `.nix` 파일을 만들고 헬퍼 함수로 감싸면 자동으로 로드됩니다.

> 내부 작동 원리(모듈 스캐닝, enable 계층, Dual-Context 등)는 [ARCHITECTURE-MODS.md](../hacking/ARCHITECTURE-MODS.md) · [다이어그램](../hacking/ARCHITECTURE-MODS.mermaid) 참조

---

## API 레퍼런스

### `mkMod pos desc bodyFn`

독립적으로 끄고 켤 수 있는 기능 단위.

| 파라미터 | 설명 |
|----------|------|
| `pos` | `__curPos` — 파일 경로에서 옵션 경로를 자동 유도 |
| `desc` | 문자열 → `mkEnableOption` 설명. `null`이면 enable 없음 (항상 활성화) |
| `bodyFn` | `{cfg, config, lib, pkgs, ...}` → `{os?, hm?, options?}` |

- 생성 옵션: `mods.<자동경로>.enable`
- `os`/`hm` 블록에 `mkIf cfg.enable` 자동 적용 (autoWrap)

### `mkModOf parentPath pos desc bodyFn`

부모 도메인이 활성화되면 기본적으로 함께 켜지는 모듈.

| 파라미터 | 설명 |
|----------|------|
| `parentPath` | 부모 경로 문자열 (예: `"mods.gui"`, `"mods.devel"`) |
| 나머지 | `mkMod`과 동일 |

- 추가 동작: `parentPath.enable = true` 시 자신의 `enable = mkDefault true`
- `mkDefault`이므로 `<hostname>.toml`에서 `false`로 오버라이드 가능

### `mkPartOf parentPath bodyFn`

자체 enable 없이 부모에 완전히 귀속되는 서브파트.

| 파라미터 | 설명 |
|----------|------|
| `parentPath` | 부모 경로 문자열 |
| `bodyFn` | `{cfg, config, lib, pkgs, ...}` → `{os?, hm?}` |

- enable 옵션 **없음** — 부모 enable에 종속
- `cfg`는 **부모** 경로의 config (자신이 아님)
- 프리셋 TOML 등록 **불필요**

### `mkNamedMod path desc bodyFn`

옵션 경로를 직접 지정하는 저수준 헬퍼. `default.nix`처럼 `__curPos`가 올바르지 않을 때 사용.

| 파라미터 | 설명 |
|----------|------|
| `path` | 옵션 경로 문자열 (예: `"mods.gui.apps.vivaldi"`) |
| 나머지 | `mkMod`과 동일 |

### `bodyFn` 파라미터

| 이름 | 설명 |
|------|------|
| `cfg` | `mkMod`/`mkModOf`: 자기 경로의 config. `mkPartOf`: 부모 경로의 config |
| `config` | 전체 NixOS/HM config 트리 |
| `lib` | `nixpkgs.lib` |
| `pkgs` | nixpkgs 패키지 세트 |
| `unstable` | unstable 채널 패키지 세트 |

### `bodyFn` 반환값

| 키 | 설명 |
|----|------|
| `os` | NixOS 설정 (`forOS=true`일 때만 적용) |
| `hm` | Home Manager 설정 (`forOS=false`일 때만 적용) |
| `options` | 추가 옵션 선언 (`enable` 외에 커스텀 옵션이 필요할 때) |

---

## Cookbook (실전 예시)

### 예시 1: 기본 — 패키지 설치 (mkMod)

가장 단순한 형태. NixOS 시스템에 서비스를 추가하고 사용자 그룹을 설정.

```nix
# mods/sys/services/docker.nix
{mkMod, ...}:
mkMod __curPos "Docker Daemon and tools" ({config, ...}: {
  os = {
    virtualisation.docker = {
      enable = true;
      autoPrune.enable = true;
    };
    users.users.${config.workspace.username}.extraGroups = ["docker"];
  };
})
```

- 파일 위치 `mods/sys/services/docker.nix` → 옵션 경로 `mods.sys.services.docker.enable`
- `os` 블록에 `mkIf cfg.enable` 자동 적용

### 예시 2: Dual-Context — NixOS + HM 동시 (mkMod)

시스템 데몬과 사용자 설정을 한 파일에서 모두 선언.

```nix
# mods/sys/services/bluetooth.nix
{mkMod, ...}:
mkMod __curPos "Bluetooth support" ({pkgs, ...}: {
  os = {
    hardware.bluetooth.enable = true;
    services.blueman.enable = true;
  };
  hm = {
    home.packages = [pkgs.bluetuith];
  };
})
```

- `os`는 NixOS 평가 시, `hm`은 Home Manager 평가 시 각각 적용
- 모듈 파일 하나로 양쪽 설정을 관리

### 예시 3: 커스텀 옵션 — options 키 활용

`enable` 외에 사용자 정의 옵션을 추가하는 패턴.

```nix
# mods/gui/base/greeter.nix
{mkModOf, ...}:
mkModOf "mods.gui" __curPos "Login greeter (greetd + tuigreet)" ({cfg, pkgs, lib, ...}: {
  options.sessionCmd = lib.mkOption {
    type = lib.types.str;
    description = "Session command passed to tuigreet --cmd";
  };
  os = {
    services.greetd = {
      enable = true;
      settings.default_session.command =
        "${pkgs.tuigreet}/bin/tuigreet --time --cmd '${cfg.sessionCmd}'";
    };
  };
})
```

- `options`에 선언한 `sessionCmd`는 `cfg.sessionCmd`로 접근
- 다른 모듈에서 `mods.gui.base.greeter.sessionCmd = "uwsm start hyprland-uwsm.desktop";`로 설정

### 예시 4: 부모 cascade — mkModOf

`mods.gui.enable = true` 시 자동으로 활성화되는 GUI 앱.

```nix
# mods/gui/apps/vivaldi.nix
{mkModOf, ...}:
mkModOf "mods.gui" __curPos "Vivaldi Browser" ({unstable, ...}: {
  hm = {
    home.packages = [
      (unstable.vivaldi.override {proprietaryCodecs = true;})
    ];
  };
})
```

- `mods.gui.enable = true` → `mods.gui.apps.vivaldi.enable = mkDefault true` (cascade)
- `<hostname>.toml`에서 `vivaldi = false`로 개별 비활성화 가능

### 예시 5: 부모 귀속 — mkPartOf

자체 toggle 없이 부모와 항상 같이 움직이는 서브파트.

```nix
# mods/gui/base/fuzzel.nix
{mkPartOf, ...}:
mkPartOf "mods.gui" ({config, ...}: {
  hm = {
    programs.fuzzel = {
      enable = true;
      settings.main = {
        terminal = config._module.args.hyprTerm;
        width = 80;
      };
    };
  };
})
```

- enable 옵션 없음 — `mods.gui.enable`이 곧 이 모듈의 활성화 조건
- `cfg`는 `config.mods.gui` (부모)를 가리킴
- 프리셋 TOML에 등록할 필요 없음

### 예시 6: 외부 데이터 — `_data/` + `builtins.readFile`

CSS, 셸 스크립트, XML 등을 별도 파일로 분리하는 패턴.

```nix
# mods/sys/base/zsh.nix
{mkPartOf, ...}:
mkPartOf "mods.sys.base" ({lib, ...}: {
  hm = {
    programs.zsh = {
      enable = true;
      initContent = lib.mkMerge [
        (lib.mkBefore (builtins.readFile ../../_data/zsh/init.pre.zsh))
        (builtins.readFile ../../_data/zsh/init.zsh)
      ];
    };
  };
})
```

- 비-Nix 파일은 `mods/_data/` 하위에 배치
- `_data/`는 `_` prefix이므로 `recursiveImportDir`에서 자동 제외
- `builtins.readFile`은 Nix 인터폴레이션 없이 파일 내용을 그대로 문자열로 읽음

### 예시 7: 항상-켜지는 모듈 — desc=null

enable 없이 모든 호스트에 적용되는 베이스 설정.

```nix
# mods/sys/base/core.nix
{mkPartOf, ...}:
mkPartOf "mods.sys.base" ({config, pkgs, ...}: {
  os = {
    users.users.${config.workspace.username} = {
      isNormalUser = true;
      extraGroups = ["wheel"];
      shell = pkgs.zsh;
    };
  };
})
```

> 이 예시는 `mkPartOf`라 desc 파라미터 자체가 없지만, `mkMod __curPos null bodyFn` 형태로도 항상-켜지는 모듈을 만들 수 있습니다. 이 경우 enable 옵션이 생성되지 않고, autoWrap도 건너뜁니다.

---

## 새 Mod 추가하기

### 1단계: `.nix` 파일 생성

`mods/<domain>/` 하위에 파일을 만들면 자동으로 모듈로 로드됩니다.

- 독립 기능 → `mkMod __curPos "설명" ({...}: {...})`
- 부모 도메인 기본 포함 → `mkModOf "mods.<domain>" __curPos "설명" ({...}: {...})`
- 부모에 완전 귀속 → `mkPartOf "mods.<domain>.<parent>" ({...}: {...})`

### 2단계: 프리셋에 등록 (`mkMod`/`mkModOf`만 해당)

`mkMod` 또는 `mkModOf`를 사용하면 `enable` 옵션이 자동 생성됩니다.
**모든 프리셋 TOML에 등록**해야 합니다:

```toml
# hosts/_preset.workstation.toml
[mods.sys.services]
my-service = false
```

```toml
# hosts/_preset.server.toml
[mods.sys.services]
my-service = true
```

> `mkPartOf`는 enable이 없으므로 프리셋 등록이 불필요합니다.

의도적으로 프리셋 밖에서 관리할 경우, `[explicitOptional]`에 등록:

```toml
[explicitOptional]
paths = ["mods.sys.services.my-internal-feature.enable"]
```

### 3단계: 검증

```bash
nixup check
```

---

## Mod 삭제하기

1. `.nix` 파일 삭제 (관련 `_data/` 파일도 함께)
2. 모든 `hosts/_preset.*.toml`에서 해당 항목 제거
3. 각 `hosts/<hostname>.toml`에서 오버라이드 항목 제거
4. `nixup check`로 검증

---

## Coverage Check 오류 대응

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
