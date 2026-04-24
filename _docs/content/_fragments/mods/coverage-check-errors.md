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
