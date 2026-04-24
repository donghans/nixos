# 아키텍처

```mermaid
--8<-- "_fragments/diagrams/architecture.mermaid"
```

---

## 네 레이어와 그 경계

```
CLI Engine  →  Metadata  →  Logic Core  →  Mods
```

각 레이어는 관심사가 다릅니다:

- **CLI Engine**: 언제, 어떻게 빌드하는가 (격리, 락, 로깅, 오케스트레이션)
- **Metadata**: 무엇이 켜져 있는가 (TOML → JSON, 프리셋 병합)
- **Logic Core**: 어떻게 NixOS 설정을 조립하는가 (Flake, 동적 host 생성, 모듈 로딩)
- **Mods**: 각 기능이 실제로 무엇을 하는가 (패키지, 서비스, dotfile)

**Metadata는 Logic Core를 모릅니다.** TOML 파일을 편집하는 사람은 Nix Flake가 어떻게 동작하는지 알 필요가 없습니다. Logic Core도 CLI Engine을 모릅니다. `flake.nix`는 `resolved.json`이 어디서 왔는지 관심 없습니다.

---

## 레이어 상세

### 1. 실행 엔진 레이어 (CLI Engine Layer)

**핵심 경로: `core/scripts/`**

이 레이어는 시스템의 모든 동작을 제어하고 외부 도구들을 오케스트레이션합니다.

- **`nixup.sh` (Dispatcher)**:
  - **역할**: 모든 명령의 통합 입구이자 빌드 오케스트레이터입니다.
  - **특징**: `nix-shell` 쉬뱅을 사용하여 `jq`, `nom` 등의 도구가 없어도 시스템을 부트스트랩할 수 있도록 설계되었습니다. 로깅(`YYYYMMDDTHHMMSS.log`)과 세션 락(`flock`)을 독점적으로 관리합니다.
  - **Shared Lib**:
    - **`lib-ui.sh`**: 색상 상수, `log_msg`/`log_exec`/`_pick`/`_check`/`_print_summary` 헬퍼. nixup·nixstrap·rnixup·rnixstrap **4개 커맨드가 공유**하는 UI 레이어.
    - **`lib-build.sh`**: `.build/` 격리 빌드 환경 구축, 세션 락(`flock`), 시그널 핸들링.
  - **nixup Task & Lib**:
    - **`nixup.lib-lock.sh`**: 기기 특성(`isRolling`)에 따른 유연한 락 파일 관리 로직.
    - **`nixup.task-resolve.py`**: TOML 소스를 읽어 Nix가 사용할 `resolved.json`과 `presets.json`을 생성하는 메타데이터 변환기.
    - **`nixup.task-*.sh`**: 실제 비즈니스 로직(빌드, 업데이트, 복구 등)을 수행하는 모듈형 스크립트.

- **`nixstrap.sh` (Local Bootstrap Engine)**:
  - nixup과 독립적인 설치 전용 서브시스템. `nixstrap` 명령으로 노출됩니다.
  - Phase 1 (입력 수집) / Phase 2 (설치 실행) 흐름 제어.
  - **Lib**: `nixstrap.lib-repo.py`(TOML 파싱, 레이블 추출), `nixstrap.lib-part.py`(파티션 범위 검증)
  - **Task**: `nixstrap.task-input.sh`(Phase 1 대화형 입력), `nixstrap.task-disk.sh`(파티션 입력), `nixstrap.task-install.sh`(Phase 2 설치 실행)

- **`rnixup.sh` (Remote Deploy Engine)**:
  - 원격 NixOS 호스트에 deploy-rs로 설정을 배포하는 도구. `rnixup` 명령으로 노출됩니다.
  - 흐름: dry-activate 미리보기 → 사용자 확인 → 전체 호스트 배포.
  - `rnixup list`: 설정된 원격 호스트 목록 출력.

- **`rnixstrap.sh` (Remote Initial Install Engine)**:
  - 원격 서버에 nixos-anywhere로 NixOS를 처음 설치하는 도구. `rnixstrap` 명령으로 노출됩니다.
  - **run_setup**: RAM 사전 감지 → 설정 확인 → TOML 파일 생성 → 공개키 추출·저장 → nixos-anywhere 설치 → hardware.nix 역복사 → deploy-rs 배포.

---

### 2. 메타데이터 레이어 (Metadata Layer)

**핵심 경로: `hosts/_base.toml`, `hosts/<hostname>.toml`, `hosts/_preset.*.toml`**

코드와 데이터를 분리하여, 사용자가 `nix` 언어를 깊게 알지 못해도 시스템 구성을 관리할 수 있게 합니다.

- **TOML 설정 원본**:
  - `_base.toml`: 전역 설정 (username, git, system, 파티션 경로 기본값)
  - `<hostname>.toml`: 호스트 설정 (type, preset, mods 오버라이드, 선택적 메모리/파티션 오버라이드)
  - `_preset.*.toml`: 프리셋 mods 정의 + explicitOptional

- **Resolver (`nixup.task-resolve.py`)**: `nixup` 빌드 시 TOML 소스를 읽어 `presets.json`(프리셋 mods + explicitOptional)과 `resolved.json`(호스트별 merged 데이터)을 생성합니다. flake.nix는 이 JSON 파일을 읽어 빌드합니다.

:::caution
`flake.nix`는 `resolved.json`이 없으면 명시적 오류를 발생시킵니다. 항상 `nixup`을 통해 빌드하세요.
:::

- **호스트별 Nix 파일**:
  - `hosts/<hostname>.nix`: 커널 파라미터, 하드웨어 모듈 등 NixOS 시스템 레벨 설정과 Home Manager 설정을 `mkHostConfiguration` 패턴으로 함께 담습니다.
  - `hosts/<hostname>.home.nix`: Home Manager 전용 추가 설정 (디스플레이 배열, 터치패드 동작 등 하드웨어 종속 개인화 로직). 분리가 필요할 때만 사용합니다.
  - `hosts/deploy/<hostname>.pub`: rnixstrap이 서버에서 추출한 SSH 공개키. deploy-rs의 root 인증에 사용됩니다.
  - `hosts/deploy/<hostname>.hardware.nix`: rnixstrap 설치 후 서버에서 역복사된 하드웨어 설정.

**리졸브 우선순위** — 병합은 2단계로 진행됩니다:

- 1단계(Python): `_base.toml` + `<hostname>.toml` + `_preset.*.toml` → `resolved.json` / `presets.json` 생성
- 2단계(Nix): flake.nix가 `presets.json`(프리셋 mods)에 `resolved.json`(host 오버라이드)을 덮어씌워 최종 병합

| 필드 | 우선순위 |
|------|---------|
| `username`, `git.*` | `<hostname>.toml` 오버라이드 가능 (기본값: `_base.toml`) |
| `system` | `<hostname>.toml` → `_base.toml` |
| `diskDevice`, `bootDevice` | `<hostname>.toml` → `_base.toml` (레이블·UUID 모두 가능) |
| `type`, `preset` | `<hostname>.toml` 필수 선언 |
| `bootLoader` | `<hostname>.toml` 선언 (enum: `systemd-boot` · `grub-bios` · `grub-uefi`, 기본: `systemd-boot`) |
| `isRemote` | resolver가 `[deploy]` 섹션 유무로 자동 판단 — 직접 선언 불필요 |
| `ramGb` | 자동 감지 (`/proc/meminfo`), `<hostname>.toml` 입력 무시 |
| `swapGb`, `tmpfsSize`, `zramPercent` | 선택적 오버라이드 (기본값: 자동 계산) |
| `stateVersion` | `<hostname>.toml` 명시 → preset 선언 → `_base.toml rollingStateVersion` (rolling 폴백) |
| `mods.*` | preset 기본값 위에 `<hostname>.toml` 오버라이드를 Nix 단계에서 병합 |

---

### 3. 로직 코어 레이어 (Logic Core Layer)

**핵심 경로: `core/flake.nix`, `core/lib/`**

- **Dynamic Generator (`core/lib/host.nix`)**: JSON 데이터를 기반으로 `nixosConfigurations`와 `homeConfigurations`를 동적으로 생성하는 메타프로그래밍 구조. `recursiveImportDir`로 `mods/` 하위 `.nix` 파일을 자동 탐색하여 모듈로 로드합니다.
- **Mods 헬퍼 라이브러리 (`core/lib/mods.nix`)**: `mkMod`, `mkNamedMod`, `mkPartOf`, `mkModOf`, `mkHostConfiguration`, `recursiveImportDir` 헬퍼를 제공합니다.
- **옵션 선언부 (`core/lib/workspace-options.nix`)**: `config.workspace` 및 `config.mods`를 선언하여 전역 설정과 기능 모듈(Mods)의 통합 옵션을 제공합니다.
- **Overlay System**:
  - **`core/overlays/wrapper.nix`**: `mkWrapper` 헬퍼. `libs`(LD_LIBRARY_PATH), `bins`(PATH), `env`(환경변수), `run`(실행 전 쉘 훅), `addFlags`(인수 추가) 등을 조합하여 주입합니다.
  - **`mods/**/*.overlay.nix`** (자동 탐색): `flake.outputs.nix`가 `mods/` 하위에서 `*.overlay.nix` 파일을 재귀 탐색하여 `customOverlays`에 자동 추가합니다.

---

### 4. 모듈 프레임워크 레이어 (Mods Layer)

**핵심 경로: `mods/`**

- **Domain-Driven Design**: `sys`, `gui`, `devel`로 도메인을 분리하여 응집도를 높였습니다.
  - `mods/sys/`: 시스템 기반 — `base`(부팅/네트워크/Zsh/Git), `fonts`, `vfs`, `services`(bluetooth/tailscale/docker/incus/networkmanager 등)
  - `mods/gui/`: GUI 환경 — `base`(Hyprland 번들: core/waybar/greeter/lock/clip), `apps`(vivaldi/slack/bitwarden 등)
  - `mods/devel/`: 개발 도구 — `base`(공통 설정), `toolchains`(node/python/fvm/devbox/jetbrains), `apps`(llm-cli/zed)
- **Shared Data (`mods/_data/`)**: `builtins.readFile`로 Nix 모듈에서 읽는 비-Nix 파일을 분리 관리합니다 — `zsh/`, `waybar/`, `incus/`, `devbox/` 등.

**데이터 흐름:**

```
.nix 파일 작성 → recursiveImportDir 자동 탐색 (core/lib/mods.nix)
  → NixOS + HM 양쪽에 주입 (host.nix)
    → mkMod/mkModOf가 enable 옵션 자동 선언
      → preset TOML + host TOML이 enable 값 결정 (flake.outputs.nix)
        → forOS 플래그에 따라 os 또는 hm 블록만 적용 → autoWrap
```

**Enable 결정 흐름 예시:**

`_preset.workstation.toml`이 `gui = true` 선언 → `mkModOf` 연쇄 활성화로 `gui.apps.vivaldi.enable = mkDefault true` → `<hostname>.toml`에서 `vivaldi = false` 오버라이드 가능 → 최종: 비활성화

> Mods 내부 원리 상세: [내부 원리](./internals.md)  
> 사용법 및 API: [Mod 만들기](../how-to/create-mod.md) · [Mod API](../reference/mod-api.md)

---

## 설계 결정 배경

### TOML로 메타데이터를 분리한 이유

"어느 기기에서 무엇이 켜져 있는가"를 Nix 코드에서 추적하는 것은 번거롭습니다. 모듈 파일을 열고, `enable = true` 구문을 찾고, import 체인을 따라가야 합니다.

TOML 분리가 제공하는 것:
1. **가시성**: Nix를 모르는 사람도 기기별 활성화 상태를 읽을 수 있습니다
2. **diff 명확성**: git diff에서 어떤 Mod가 켜졌는지 즉각 파악됩니다
3. **프리셋 분리**: 워크스테이션/서버 기본 조합을 별도 파일로 관리하여 개별 호스트 파일을 간결하게 유지합니다

:::note
TOML은 Nix 평가 시점에 없으므로, `nixup`이 빌드 전에 TOML → JSON 변환을 수행합니다. 이것이 `nix build`를 직접 부를 수 없는 이유입니다.
:::

### 빌드 격리(`path:` 모드)를 도입한 이유

이 저장소는 하나의 `flake.nix`가 rolling 기기와 stable 기기를 동시에 관리합니다. Rolling 기기는 매 빌드마다 새 lock을 받아야 하고, stable 기기는 `<hostname>.lock`에 고정된 버전을 써야 합니다. 둘을 같은 `flake.lock`으로 관리할 수 없습니다.

또한 lock 파일을 저장소에 커밋하면 아직 커밋하지 않은 설정 변경을 테스트할 수 없습니다 (Nix는 기본적으로 git-tracked 파일만 평가하기 때문입니다).

해결책: 빌드 전에 소스를 `.build/` 디렉터리에 물리 복사하고, `path:` 접두사를 붙여 nix를 호출합니다. 부수 효과로, 커밋하지 않은 변경도 즉시 빌드할 수 있습니다.

### 하이브리드 lock 전략의 이유

Rolling 기기와 stable 기기가 lock 파일을 공유하면 한쪽이 항상 불편합니다:

- 공유하면 rolling 기기가 stable 버전에 묶임
- 기기마다 lock을 두면 rolling 기기도 매번 수동으로 업데이트해야 함

해결책: Rolling 기기(`isRolling = true`)는 공용 `_rolling.lock`을 씁니다. Stable 기기는 각자의 `<hostname>.lock`을 씁니다.

### Mods 프레임워크를 직접 만든 이유

표준 NixOS 모듈로 "이 기능을 끄고 싶다"를 표현하려면 옵션 선언, `mkIf cfg.enable`, enable 조건부 활성화를 모든 기능 단위마다 반복해야 합니다. `mkMod`는 이 보일러플레이트를 없앱니다.

`__curPos` (파일 위치 정보)를 이용해 옵션 경로를 자동 유도하므로, 경로를 직접 선언할 필요가 없습니다. `recursiveImportDir`이 `mods/` 하위를 자동 탐색하므로 `flake.nix`에 import를 추가할 필요도 없습니다.

### os/hm 블록을 같은 파일에 두는 이유

**locality(인접성)** 때문입니다. docker Mod를 수정할 때, 시스템 레벨 설정과 사용자 레벨 설정이 같은 파일에 있어야 함께 추론할 수 있습니다. `forOS` 플래그(NixOS 평가 시 `true`, Home Manager 평가 시 `false`)로 같은 파일이 두 맥락에서 올바르게 로드됩니다.

### Coverage Check를 빌드 타임에 넣은 이유

새로운 Mod를 추가하면서 프리셋 TOML에 기재하는 것을 잊으면, 그 Mod는 모든 호스트에서 조용히 꺼진 채로 방치됩니다. 런타임에는 아무 오류가 없기 때문에 인지하기 어렵습니다. Coverage Check는 이 문제를 빌드 타임에 잡습니다.

"형제 완전성 검사"는 `mods.gui.apps` 그룹에서 vivaldi만 프리셋에 명시하고 나머지를 누락했을 때, "의도적으로 관리 중인가, 실수로 누락됐나"를 구분할 수 없는 문제를 방지합니다. 그룹 내에서 하나를 명시했으면 전부 명시하도록 강제합니다.

---

## 디렉터리 구조

```text
/
├── core/                    # Flake 진입점(flake.nix), 빌더(lib/), 엔진 스크립트(scripts/)
│   ├── lib/                 # host.nix, mods.nix, workspace-options.nix, preset.nix
│   ├── scripts/             # nixup 관리 CLI, nixstrap 설치 스크립트
│   ├── overlays/            # mkWrapper 오버레이 (wrapper.nix)
│   ├── iso.nix              # ISO 전용 통합 설정
│   └── iso.nixstrap.nix     # ISO nixstrap 인스톨러 주입 로직
├── hosts/                   # 호스트별 설정 (평탄 구조)
│   ├── _base.toml           # 전역 설정 원본 (username, git, system)
│   ├── _preset.workstation.toml  # 워크스테이션 프리셋
│   ├── _preset.server.toml  # 서버 프리셋
│   ├── _preset.iso.toml     # ISO 프리셋
│   ├── <hostname>.toml      # 호스트 메타데이터
│   ├── <hostname>.nix       # 호스트 전용 NixOS + Home Manager 설정
│   └── deploy/              # 원격 호스트 전용 파일
│       ├── <hostname>.pub          # SSH 공개키
│       └── <hostname>.hardware.nix # 하드웨어 설정
├── mods/                    # Mods 프레임워크 (3개 도메인)
│   ├── sys/                 # 시스템 기반
│   ├── gui/                 # GUI 환경
│   ├── devel/               # 개발 도구
│   └── _data/               # 비-Nix 데이터 파일
├── _docs/                   # 문서 저장소
└── .locks/                  # 시스템 안정성을 위한 락 파일 관리
```
