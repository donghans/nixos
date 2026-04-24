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
