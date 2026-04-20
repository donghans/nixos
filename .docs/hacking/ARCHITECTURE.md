# 🏗️ 프로젝트 아키텍처 (Internal Components)

이 프로젝트는 유지보수성과 확장성을 극대화하기 위해 명확한 **관심사 분리(Separation of Concerns)**를 실천하고 있습니다.

> **다이어그램**: [ARCHITECTURE.mermaid](./ARCHITECTURE.mermaid) (레이어 구조 및 데이터 흐름)

---

## 1. 실행 엔진 레이어 (CLI Engine Layer)
**핵심 경로: `core/scripts/`**

이 레이어는 시스템의 모든 동작을 제어하고 외부 도구들을 오케스트레이션합니다.

- **`nixup.sh` (Dispatcher)**:
  - **역할**: 모든 명령의 통합 입구이자 빌드 오케스트레이터입니다.
  - **특징**: `nix-shell` 쉬뱅을 사용하여 `jq`, `nom` 등의 도구가 없어도 시스템을 부트스트랩할 수 있도록 설계되었습니다. 로깅(`YYYYMMDDTHHMMSS.log`, 예: `20260405T120000.log`)과 세션 락(`flock`)을 독점적으로 관리합니다.
- **Task & Lib**:
  - **`nixup.lib-ui.sh`**: 색상 상수, `log_msg`/`log_exec` 헬퍼, 초기화 배너 출력.
  - **`nixup.lib-build.sh`**: `.build/` 격리 빌드 환경 구축 로직. 소스를 물리 복사하고 nix를 `path:` 모드로 호출하여 git 추적 없이 순수 평가를 수행합니다.
  - **`nixup.lib-lock.sh`**: 기기 특성(`isRolling`)에 따른 유연한 락 파일 관리 로직.
  - **`nixup.task-resolve.py`**: TOML 소스(`hosts/_base.toml`, `hosts/<hostname>.toml`, `hosts/_preset.*.toml`)를 읽어 Nix가 사용할 `resolved.json`과 `presets.json`을 생성하는 메타데이터 변환기.
  - **`nixup.task-*.sh`**: 실제 비즈니스 로직(빌드, 업데이트, 복구 등)을 수행하는 모듈형 스크립트.
- **`nixstrap.sh` (Bootstrap Engine)**:
  - nixup과 독립적인 설치 전용 서브시스템. `nixstrap` 명령으로 노출됩니다. Phase 1/2 흐름 제어 및 공유 상태 관리.
  - **Phase 1 (입력 수집)**: 저장소 클론 또는 로컬 경로 사용, 호스트·파티션·프리셋 선택, 비밀번호 입력. 이전 세션 파라미터(`/root/nixstrap-params.env`) 복원 지원.
  - **Phase 2 (설치 실행)**: 파티셔닝(EFI+Btrfs) → 서브볼륨 생성 → 마운트 → 하드웨어 감지 → `nixos-install` → 후처리(저장소 이동·심볼릭 링크·비밀번호 적용) 순서 실행.
  - **Lib**:
    - `nixstrap.lib-ui.sh`: 색상 상수, 로깅 헬퍼, 화살표 키 선택 UI.
    - `nixstrap.lib-repo.py`: TOML 파싱, 디스크 레이블 추출 등 레포지토리/설정 헬퍼.
    - `nixstrap.lib-part.py`: 빈 공간 탐색, 파티션 범위 검증 등 디스크/파티션 헬퍼.
  - **Task**:
    - `nixstrap.task-input.sh`: Phase 1 대화형 입력 함수 (저장소·호스트·프리셋·비밀번호·세션 관리).
    - `nixstrap.task-disk.sh`: Phase 1 디스크·파티션 입력 함수 (`ask_partitions`).
    - `nixstrap.task-install.sh`: Phase 2 설치 실행 함수.

---

## 2. 메타데이터 레이어 (Metadata Layer)
**핵심 경로: `hosts/_base.toml`, `hosts/<hostname>.toml`, `hosts/_preset.*.toml`**

코드와 데이터를 분리하여, 사용자가 `nix` 언어를 깊게 알지 못해도 시스템 구성을 관리할 수 있게 합니다.

- **TOML 설정 원본**: `_base.toml`(전역: username, git, system, 파티션 경로 기본값), `<hostname>.toml`(호스트: type, preset, mods 오버라이드, 선택적 메모리/파티션 오버라이드), `_preset.*.toml`(프리셋 mods 정의 + explicitOptional)을 TOML로 선언합니다.
- **Resolver (`nixup.task-resolve.py`)**: `nixup` 빌드 시 TOML 소스를 읽어 `presets.json`(프리셋 mods + explicitOptional)과 `resolved.json`(호스트별 merged 데이터)을 생성합니다. flake.nix는 이 JSON 파일을 읽어 빌드합니다.
- **직접 nix 실행 금지**: `flake.nix`는 `resolved.json`이 없으면 명시적 오류를 발생시킵니다. 항상 `nixup`을 통해 빌드하세요.
- **호스트별 Nix 파일**: TOML로 표현하기 어려운 하드웨어 고유 설정을 직접 작성하는 공간입니다.
  - `hosts/<hostname>.nix`: 커널 파라미터, 하드웨어 모듈 등 NixOS 시스템 레벨 설정과 Home Manager 설정을 `mkHostConfiguration` 패턴으로 함께 담습니다.
  - `hosts/<hostname>.home.nix`: Home Manager 전용 추가 설정 (디스플레이 배열, 터치패드/리드스위치 동작, 절전 타이머 등 하드웨어 종속 개인화 로직). 분리가 필요할 때만 사용합니다.

**리졸브 우선순위** — 병합은 2단계로 진행됩니다.

- 1단계(Python): `_base.toml` + `<hostname>.toml` + `_preset.*.toml` → `resolved.json` / `presets.json` 생성
- 2단계(Nix): flake.nix가 `presets.json`(프리셋 mods)에 `resolved.json`(host 오버라이드)을 덮어씌워 최종 병합

| 필드 | 우선순위 |
|------|---------|
| `username`, `git.*` | `<hostname>.toml` 오버라이드 가능 (기본값: `_base.toml`) |
| `system` | `<hostname>.toml` → `_base.toml` |
| `diskDevice`, `bootDevice` | `<hostname>.toml` → `_base.toml` (파티션 경로. 레이블·UUID 모두 가능) |
| `type`, `preset` | `<hostname>.toml` 필수 선언 |
| `ramGb` | 자동 감지 (`/proc/meminfo`), `<hostname>.toml` 입력 무시 |
| `swapGb`, `tmpfsSize`, `zramPercent` | 선택적 오버라이드 (기본값: 자동 계산) |
| `stateVersion` | `<hostname>.toml` 명시 → preset 선언 → `_base.toml rollingStateVersion` (rolling 폴백, 항상 non-null) |
| `mods.*` | preset 기본값 위에 `<hostname>.toml` 오버라이드를 Nix 단계에서 병합 |

---

## 3. 로직 코어 레이어 (Logic Core Layer)
**핵심 경로: `core/flake.nix`, `core/lib/`**

시스템 설정의 두뇌에 해당하며, Nix Flake의 강력한 기능을 활용해 복잡한 패키징과 모듈성을 구현합니다.

- **Dynamic Generator (`core/lib/builders.nix`)**: JSON 데이터를 기반으로 `nixosConfigurations`와 `homeConfigurations`를 동적으로 생성해내는 **메타프로그래밍 구조**와 빌더 팩토리입니다. `recursiveImportDir`로 `mods/` 하위 `.nix` 파일을 자동 탐색하여 모듈로 로드합니다.
- **Mods 헬퍼 라이브러리 (`core/lib/mods-lib.nix`)**: `mkMod`, `mkNamedMod`, `mkPartOf`, `mkModOf`, `recursiveImportDir` 헬퍼를 제공합니다. `_`로 시작하는 디렉터리/파일, `*.home.nix`, `*.overlay.nix`, `default.nix`를 자동 제외하고 나머지 `.nix`를 모두 모듈로 로드합니다.
- **옵션 선언부 (`core/lib/workspace-options.nix`)**: `config.workspace` 및 `config.mods`를 선언하여 전역 설정과 기능 모듈(Mods)의 통합 옵션을 제공합니다.
- **Overlay System**:
  - **`core/lib/mk-wrapper.nix`**: `mkWrapper` 헬퍼. 패키지에 런타임 환경 변수, 라이브러리 경로(`libs`), PATH 바이너리(`bins`), 환경변수(`env`), 실행 전 쉘 훅(`run`), 추가 인수(`addFlags`) 등을 조합하여 주입합니다.
  - **`mods/**/*.overlay.nix`** (자동 탐색): `flake.outputs.nix`가 `mods/` 하위에서 `*.overlay.nix` 파일을 재귀 탐색하여 `customOverlays`에 자동 추가합니다. nixpkgs 패키지를 overlay로 직접 패치할 때 사용하며, 관련 모듈 옆에 위치하여 locality를 유지합니다. 현재 `mods/devel/toolchains/`에 `jetbrains.overlay.nix`, `node.overlay.nix`, `fvm.overlay.nix` 3개가 등록되어 있습니다.

---

## 4. 모듈 프레임워크 레이어 (Mods Layer)
**핵심 경로: `mods/`**

실제 시스템의 살점이 되는 부분이며, **Mods 프레임워크** 기반으로 설계되었습니다.

- **Domain-Driven Design**: `sys`, `gui`, `devel`로 도메인을 분리하여 응집도를 높였습니다.
  - `mods/sys/`: 시스템 기반 — `base`(부팅/네트워크/Zsh/Git), `fonts`, `vfs`, `services`(bluetooth/tailscale/docker/incus/networkmanager 등), `utils/nfd`
  - `mods/gui/`: GUI 환경 — `base`(Hyprland 번들: core/waybar/greeter/lock/clip), `apps`(vivaldi/slack/bitwarden/speedcrunch/incus-vm), `utils`(notify-logger)
  - `mods/devel/`: 개발 도구 — `base`(공통 설정), `toolchains`(node/python/fvm/devbox/jetbrains), `apps`(llm-cli/zed)
- **Mod 헬퍼 패턴**:
  - `mkMod` / `mkNamedMod`: 독립 기능 단위. `mods.<domain>.<name>.enable`을 선언하며, false일 때 완전히 비활성화됩니다.
  - `mkPartOf "parent.path"`: 자체 enable 없이 부모에 완전히 귀속되는 서브 파트.
  - `mkModOf "parent.path" __curPos "설명"`: 부모가 활성화되면 기본 활성화되는 자식 모듈(역방향 cascade). enable 옵션 자동 생성.
- **프리셋 시스템 (`hosts/_preset.*.toml`)**: `_preset.workstation.toml`(개발 환경), `_preset.server.toml`(서버 환경), `_preset.iso.toml`(설치 미디어) 등 용도별 프리셋이 정의되어 있습니다. flake.nix가 이를 읽어 호스트별 mods와 병합하여 적용합니다. `<hostname>.toml`에는 프리셋 기본값에서 변경할 항목만 기재합니다.
- **Mods Coverage Check**: flake.nix가 호스트별로 `mk-preset.nix` 기반 coverageModule을 주입합니다. ISO(`custom-iso`, `custom-iso-aarch64`) 빌드도 포함하여 두 가지 검사를 수행합니다: ① 선언됐지만 preset에 없는 옵션 감지, ② 같은 그룹 내 옵션 중 일부만 명시 시 오류(형제 완전성 검사).
- **Shared Data (`mods/_data/`)**: `builtins.readFile`로 Nix 모듈에서 읽는 비-Nix 파일을 분리 관리합니다 — `zsh/` (셸 초기화 스크립트), `waybar/` (CSS), `incus/` (XML·PS1), `devbox/` (설정 템플릿) 등.

### 데이터 흐름

```
.nix 파일 작성 → recursiveImportDir 자동 탐색 (core/lib/mods-lib.nix)
  → NixOS + HM 양쪽에 주입 (builders.nix)
    → mkMod/mkModOf가 enable 옵션 자동 선언
      → preset TOML + host TOML이 enable 값 결정 (flake.outputs.nix)
        → isNixOS 플래그에 따라 os 또는 hm 블록만 적용 → autoWrap
```

### Enable 결정 흐름 예시

`_preset.workstation.toml`이 `gui = true` 선언 → `mkModOf` cascade로 `gui.apps.vivaldi.enable = mkDefault true` → `<hostname>.toml`에서 `vivaldi = false` 오버라이드 가능 → 최종: 비활성화

> 내부 원리 상세: [ARCHITECTURE-MODS.md](./ARCHITECTURE-MODS.md) · [다이어그램](./ARCHITECTURE-MODS.mermaid)
> 사용법 및 API: [MODS.md](../manual/MODS.md)
