# Mod API 레퍼런스

> 실전 예시 및 추가/삭제 절차는 [Mod 만들기](../how-to/create-mod.md) 참조  
> 내부 작동 원리(스캐닝, enable 계층, autoWrap 등)는 [내부 원리](../explanation/internals.md) 참조

---

--8<-- "_fragments/mods/helper-table.md"

**Dual-Context**: 모든 모듈은 NixOS(`os` 블록)와 Home Manager(`hm` 블록) 양쪽에 자동 로드됩니다. 한 파일에서 `os = {...}; hm = {...};`를 선언하면 각 컨텍스트에 맞게 분기 적용됩니다.

---

## API 레퍼런스

각 헬퍼의 시그니처와 파라미터 상세입니다. Cookbook 예시에서 사용한 패턴의 정확한 동작을 확인할 때 참조하세요.

### `mkMod pos desc bodyFn`

독립적으로 끄고 켤 수 있는 기능 단위.

| 파라미터 | 설명 |
|----------|------|
| `pos` | `__curPos` — 파일 경로에서 옵션 경로를 자동 유도 |
| `desc` | 문자열 → `mkEnableOption` 설명 |
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
