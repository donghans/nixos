---
name: donghans-sbox-init
description: 프로젝트 하나를 위한 격리 컨테이너(sbox ct)를 만들기 전에, 프로젝트 파일(.nvmrc·package.json·락 파일·docker-compose.yml·rust-toolchain·go.mod 등)을 읽어 도구 버전을 추론하고 버전 매니페스트(~/.config/sbox/manifests/<프로젝트>.toml)와 `sbox.sh create` 인자(flavor·릴리스)를 제안하는 스킬. 「이 프로젝트용 sbox 만들어줘」「샌드박스 환경 맞춰줘」「프로젝트 버전 매니페스트」「sbox init」「격리 환경 초기 설정」을 말할 때 먼저 읽는다. 프로젝트 저장소에는 파일을 추가하지 않는다.
---

# donghans-sbox-init — 프로젝트 → 버전 매니페스트 → sbox ct 제안

정본 설계: ctx `plan/dev-sandbox-pilot` §29(도구 층·매니페스트), §23(체크리스트 S5·S34·S36). **이 스킬은 만드는 것을 제안하고, 컨테이너 생성·삭제는 사용자 확인 뒤에만 한다.** 프로젝트 저장소를 수정하지 않는다(매니페스트는 저장소 밖 `~/.config/sbox/manifests/`).

## 명령(저장소 `~/nixos` 안)
- `python3 ~/nixos/core/sbox/tools.py infer <저장소>` — 프로젝트 파일에서 추론한 도구 스펙(JSON, 읽기 전용).
- `python3 ~/nixos/core/sbox/tools.py plan --repo <저장소> [--update] [--tool node=22.11.0]` — 매니페스트를 만들거나 갱신하고 **정확한 버전을 `[resolved]` 에 고정**(이미 고정된 스펙은 그대로 재사용, `--update` 로만 다시 해석). 매니페스트를 쓰므로 호스트 홈의 파일이 바뀐다 — 사용자가 이 스킬을 부른 것을 허락으로 본다.
- `bash ~/nixos/core/scripts/sbox.sh releases [debian|ubuntu]` — 쓸 수 있는 릴리스와 지원 상태.
- `bash ~/nixos/core/scripts/sbox.sh create --kind ct --flavor F [--release R] [--legacy] [--nesting] NAME` 와 `sbox.sh tools NAME --from-repo <저장소>`.

## 절차
1. **프로젝트 파일 읽기(읽기 전용)**: 루트의 `.nvmrc`·`.node-version`·`package.json`(`engines`·`packageManager`·`prisma`·`@prisma/client`·`playwright`·`@playwright/test` 버전)·락 파일, `Cargo.toml`·`rust-toolchain(.toml)`, `go.mod`·`go.work`, `docker-compose*.yml`(이미지 태그: postgres·redis 등), `.tool-versions`, `pyproject.toml`·`.python-version`. 비밀 파일(`.env*`)은 읽지 않는다.
2. **`tools.py infer` 로 도구 층이 지원하는 것을 추론**(v1: node 만). 지원하지 않는 도구(Rust·Go·Python·PostgreSQL·Compose 등)는 **「미지원 — 수동 필요」로 보고**하고 감지한 버전만 적는다(추측으로 매니페스트에 넣지 않는다).
3. **flavor·릴리스 제안**: 기본 `debian` 13. 근거를 적는다 — 예: 서버 배포판이 Ubuntu 면 `ubuntu` 와 해당 릴리스, 옛 Node/Prisma 면 그 시기의 릴리스(EOL 이면 `--legacy` 필요), Playwright 공식 지원 릴리스(`releases.toml` 의 note), E2E·Docker 가 필요하면 `--nesting`. 근거 없는 선택은 「기본값」이라고 말한다.
4. **사용자에게 제안 보고** — 한 번에 모아서: 추론된 도구와 출처 파일, 정확히 고정될 버전(`plan` 이 해석한 값), 미지원 도구 목록, 제안 `create` 명령과 이름(`sbox-ct-<flavor><버전(점 제거)>-<프로젝트>`). 확인 전에 컨테이너를 만들지 않는다.
5. **확인되면**: `tools.py plan` 으로 매니페스트 기록 → `sbox.sh create …` → `sbox.sh tools <이름> --from-repo <저장소>` → 컨테이너 안에서 `node -v` 등으로 확인하고 결과를 보고한다.
6. **재현성**: `.nvmrc` 의 `22` 같은 느슨한 스펙은 처음 풀린 정확한 버전이 `[resolved]` 에 고정된다(마이너·패치로 동작이 달라지는 것을 막는 사용자 요구). 사용자가 새 패치를 원할 때만 `--update`. 정확한 버전을 직접 정하려면 `[override]`(또는 `--tool node=22.11.0`).

## 하지 않는 것
- 프로젝트 저장소에 `.nvmrc`·`devbox.json` 같은 파일을 추가·수정하지 않는다(팀원과의 마찰 방지 — 사용자 방침).
- Prisma 엔진·Playwright 브라우저는 npm 이 받는 프로젝트 의존성이라 도구 층 대상이 아니다. 브라우저는 규칙대로 Docker 안(또는 `plan/dev-sandbox-pilot` §27·§28 의 Gentoo 바이너리 경로) — 이 스킬은 필요 여부만 짚는다.
- 시험 기록·측정 결과를 프로젝트 폴더에 남기지 않는다(ctx `propose`).
