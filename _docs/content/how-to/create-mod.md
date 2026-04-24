# Mod 만들기

이 프로젝트의 모든 기능은 `mods/` 디렉터리의 모듈(Mod)로 구성됩니다. `.nix` 파일을 만들고 헬퍼 함수로 감싸면 자동으로 로드됩니다.

---

## 개요

Mod를 만드는 과정은 4단계입니다:

```
1. .nix 파일 생성     mods/<domain>/ 하위에 파일을 놓는다
2. 헬퍼로 감싸기       mkMod / mkModOf / mkPartOf 중 선택
3. 프리셋에 등록       _preset.*.toml에 enable 항목 추가 (mkPartOf는 불필요)
4. 검증              nixup check
```

---

--8<-- "_fragments/mods/helper-table.md"

---

--8<-- "_fragments/mods/cookbook-examples.md"

---

--8<-- "_fragments/mods/add-delete-procedure.md"

---

--8<-- "_fragments/mods/coverage-check-errors.md"

---

> 내부 작동 원리(모듈 스캐닝, enable 계층, Dual-Context 등)는 [내부 원리](../explanation/internals.md) 참조  
> 헬퍼 함수 시그니처는 [Mod API](../reference/mod-api.md) 참조
