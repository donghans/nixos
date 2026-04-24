# nixup 명령어 레퍼런스

`nixup`은 `nix` 커맨드를 베이스로 빌드 격리, 자동 로깅, 패키지 복구 로직 등을 추가한 통합 관리 도구입니다.

> 상황별 활용 사례는 [시스템 관리](../how-to/manage-system.md) 참조

---

## 기본 명령어 구조

```bash
nixup [subcommand] [flags]
```

- **`subcommand`**: 작업 종류 (`os`, `home`, `iso`, `fix`, `check`, `update`, `clean`)
  - 생략 시 `os + home` (시스템 + 사용자 설정 동시 적용)이 기본값입니다.
- **`flags`**: 동작 제어 옵션 (`--try`, `--stage`, `--build` 등)

:::note
**대상 호스트 결정**: `.env`의 `NIXUP_LAST_HOST` 값을 우선 사용합니다. 없으면 OS 호스트명(`hostname -s`)으로 자동 감지합니다. switch/`--try`/`--stage` 실행 후에는 해당 호스트가 `.env`에 자동으로 저장됩니다.
:::

---

--8<-- "_fragments/nixup-commands-detail.md"

---

--8<-- "_fragments/nixup-log-paths.md"
