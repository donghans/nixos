# Mods Framework 리팩터링 기록

이 문서는 리팩터링이 완료된 시점에서 돌아보며 쓴 기록이다.
무엇을 바꿨는지보다, **왜 바꿨는지**와 **어떤 판단이 누적됐는지**를 남긴다.

---

## 출발점: 무엇이 문제였나

리팩터링 전 구조는 다음과 같았다.

```
lib/
├── _base/
│   ├── default.nix          # 기본 시스템 설정
│   ├── default.home.nix     # Zsh, Git, Atuin 등
│   ├── hyprland.nix         # GUI (OS 레벨)
│   └── hyprland.home.nix    # GUI (Home Manager)
│       └── hyprland.home/   # Waybar, Fuzzel, Kitty 등 각각
└── developer.nix            # 개발자 모드 (마스터 스위치)
    └── developer.home.nix

dev/
└── beelink-ser7-co/
    ├── configuration.nix    # lib/_base + lib/developer import
    ├── home.nix
    └── _hardware.nix
```

겉으로는 분리된 것처럼 보이지만, 실제로는 import 체인 끝에 모든 것이 묶여있었다.
무엇이 켜져 있는지 파악하려면 파일을 따라가야 했고,
새 기기를 추가할 때 어디를 얼마나 복사해야 할지 불분명했다.

문제를 한 줄로 요약하면: **"설정이 선언된 것처럼 보이지만 실제로는 절차적이었다."**

---

## 핵심 설계 원칙

리팩터링을 진행하면서 수렴된 판단들이다.

### 1. 데이터가 코드보다 먼저다

호스트 설정의 본질은 "이 기기에서 무엇을 켤 것인가"이다.
Nix 코드로 이걸 표현하면 로직과 데이터가 섞인다.
TOML로 분리하면 데이터는 데이터답게, Nix는 그것을 해석하는 엔진으로만 존재한다.

```toml
# hosts/beelink-ser7-co/host.toml
isLaptop = false
ramGb    = 32
preset   = "workstation"
```

이 파일을 보면 이 기기에 대해 알아야 할 것을 전부 알 수 있다.
`configuration.nix`는 이제 하드웨어 특화 설정만 담는다.

### 2. 프리셋은 "무엇을 쓸 것인가"의 명세서다

기기마다 mods를 하나씩 활성화하는 것은 반복 작업이다.
"워크스테이션 환경"이라는 개념이 존재한다면, 그것을 하나의 단위로 선언하는 게 맞다.

```toml
# mods/_preset/workstation.toml
[mods.sys]
base = true
[mods.sys.services]
bluetooth = true
networkmanager = true
tailscale = true
docker = true
[mods.gui]
enable = true
[mods.gui.apps]
vivaldi = true
slack   = true
...
```

기기의 `host.toml`에는 `preset = "workstation"` 한 줄이면 충분하다.
프리셋 기본값에서 변경할 항목만 `host.toml`의 `[mods]` 섹션에 추가한다.

### 3. 도메인은 책임의 경계다

sys, gui, devel 세 도메인의 경계는 단순한 파일 분류가 아니다.

- **sys**: 시스템이 부팅하고 네트워크를 사용하기 위한 기반. GUI가 없어도 존재해야 한다.
- **gui**: Hyprland를 포함한 그래픽 환경 전체. 활성화하면 fonts와 vfs를 자동으로 끌고 온다.
  (nemo가 동작하려면 vfs가 필요하고, GUI에 CJK 폰트가 없으면 반쪽짜리다.
  이건 워크스테이션 전용 옵션이 아니라 gui 자체의 내부 의존성이다.)
- **devel**: 개발 도구 일체. 시스템과 독립적으로 켜고 끌 수 있다.

gui가 fonts와 vfs를 자동 활성화하는 것은 `gui/default.nix`의 내부 로직이며,
프리셋의 `[explicitOptional]`에 명시해 커버리지 체크에서 제외한다.

### 4. 하나의 모듈이 두 컨텍스트를 처리한다

리팩터링 전에는 `hyprland.nix`(OS)와 `hyprland.home.nix`(HM)가 별개 파일이었다.
기능을 추가하거나 수정할 때 두 파일을 모두 건드려야 했다.

After에서는 하나의 모듈이 `isNixOS` 플래그로 분기한다.

```nix
# mods/gui/core/default.nix
{ isNixOS, config, lib, ... }:
mkIf cfg.enable {
  # isNixOS = true: nhw os switch
  # isNixOS = false: nhw home switch
}
```

`nhw home switch`는 Home Manager 컨텍스트로 실행되어 시스템 권한 없이도
사용자 환경을 갱신할 수 있다. 이것이 Dual-Context의 실제 가치다.

### 5. nhw가 유일한 빌드 진입점이다

`flake.nix`는 `resolved.json`이 없으면 명시적 오류를 낸다.
이 설계는 의도적이다. `nix build .#hostname`을 직접 실행하는 것을 막는다.

빌드 전에 반드시 `nhw.resolve.py`가 실행되어야 하기 때문이다.
resolver가 TOML을 읽어 `resolved.json`과 `presets.json`을 생성하고,
flake.nix는 그 결과물을 소비한다. 이 순서가 보장되어야 한다.

```
TOML 소스
  hosts/base.toml           (username, git, system)
  hosts/<host>/host.toml    (isLaptop, ramGb, preset, mods 오버라이드)
  mods/_preset/*.toml       (프리셋 mods + explicitOptional)
      ↓ nhw.resolve.py
presets.json                (preset별 mods + explicitOptional)
resolved.json               (host별 merged 데이터)
      ↓ flake.nix (nhw 경유)
nixosConfigurations / homeConfigurations
```

### 6. Coverage Check는 Strict Governance의 대안이다

초기 설계에는 "gui/devel은 프리셋 없이 직접 활성화 불가"라는 Strict Governance가 있었다.
하지만 이것은 오히려 과도한 제약이었다.
필요에 따라 수동으로 도메인을 켜는 것 자체는 문제가 아니다.

진짜 문제는 **"새 옵션을 추가하면서 프리셋을 갱신하는 것을 잊는 것"**이다.

Coverage Check는 이것만 잡는다.
`workspace-options.nix`에 선언된 `enable` 옵션이 어떤 프리셋에도 없으면 빌드 에러를 낸다.
explicitOptional에 등록하는 것도 "의도적 제외"로 인정한다.

```nix
# core/lib/mk-preset.nix
# flake.nix가 per-host로 주입하는 커버리지 체크 모듈
{ lib, options, presetName, presetsJsonPath, excludePrefixes ? [] }:
# ...
# uncovered가 비어있지 않으면 빌드 타임 에러
```

root@hostname은 sys 모듈만 로드하므로 `excludePrefixes = ["mods.gui" "mods.devel"]`로 제외한다.

---

## Before → After 요약

| | 리팩터링 전 | 리팩터링 후 |
|---|---|---|
| **설정 위치** | `lib/` (단일 폴더) | `mods/` (sys / gui / devel 도메인) |
| **호스트 정의** | `dev/hostname/*.nix` | `hosts/hostname/host.toml` + 최소 nix |
| **메타데이터** | `specialArgs`로 주입 | `config.workspace.*` 전역 옵션 (SSOT) |
| **기능 선택** | import 체인 | `preset = "workstation"` + 오버라이드 |
| **Dual-Context** | OS용/HM용 파일 분리 | 단일 모듈 내 `isNixOS` 분기 |
| **거버넌스** | 없음 | Coverage Check (누락 감지) |
| **빌드 진입점** | `nix` 직접 호출 가능 | nhw 전용 (resolved.json 없으면 에러) |
| **메타데이터 형식** | `_info.json` (JSON) | `base.toml` + `host.toml` (TOML) |

---

## 최종 디렉터리 구조

```
nixos/
├── core/
│   ├── flake.nix                    # 메인 진입점 (resolved.json 필수)
│   ├── lib/
│   │   ├── builders.nix             # mkHost, mkHostContext 팩토리
│   │   ├── mk-preset.nix            # 커버리지 체크 모듈 팩토리
│   │   ├── mk-wrapper.nix           # 패키지 래핑 헬퍼
│   │   └── workspace-options.nix    # config.workspace + config.mods 옵션 선언
│   ├── scripts/
│   │   ├── nhw.sh                   # 통합 CLI 진입점
│   │   ├── nhw.resolve.py           # TOML → resolved.json + presets.json
│   │   ├── nhw.lib-build.sh         # 격리 빌드 환경 구축
│   │   ├── nhw.lib-lock.sh          # rolling/stable 락 전략
│   │   ├── nhw.task-check.sh        # 정적 분석 + 빌드 검증
│   │   └── nhw.task-*.sh            # 기타 태스크
│   ├── iso.nix                      # ISO 전용 NixOS 설정
│   └── iso.home.nix                 # ISO 전용 Home Manager 설정
│
├── mods/
│   ├── default.nix                  # sys + gui + devel 로드
│   ├── sys/
│   │   ├── base/                    # Zsh, Atuin, Git, CLI 기반
│   │   ├── fonts/                   # CJK + Nerd Fonts
│   │   ├── vfs/                     # GVFS, Udisks2, trash-cli
│   │   ├── services/                # bluetooth, networkmanager, tailscale, docker
│   │   └── utils/nfd/               # macOS 파일명 교정
│   ├── gui/
│   │   ├── core/                    # Hyprland 번들 (OS + HM)
│   │   ├── apps/                    # vivaldi, slack, bitwarden
│   │   └── utils/                   # notifications_logger
│   ├── devel/
│   │   ├── node/, python/, fvm/     # 언어 툴체인
│   │   ├── devbox/, llm-cli/, zed/  # 도구
│   │   └── jetbrains/               # IDE (android-studio 포함)
│   └── _preset/
│       └── workstation.toml         # 워크스테이션 환경 선언
│
├── hosts/
│   ├── base.toml                    # 전역: username, git, system
│   ├── hardware/                    # nixos-generate-config 결과물
│   └── <hostname>/
│       ├── host.toml                # 호스트: isLaptop, ramGb, preset, mods 오버라이드
│       ├── configuration.nix        # 하드웨어 특화 설정만
│       └── home.nix                 # 호스트별 HM 커스터마이징만
│
└── .locks/
    ├── _rolling.lock
    └── <hostname>.lock
```

---

## 이 구조가 지향하는 것

새 기기를 추가할 때 `host.toml` 한 장에 `preset = "workstation"`을 쓰면
그 기기는 즉시 완전한 개발 환경을 갖는다.

프리셋에서 벗어나는 항목만 `[mods]` 섹션에 추가하거나 제거한다.
`configuration.nix`와 `home.nix`는 그 기기에서만 유효한 것들, 즉 하드웨어 설정과
모니터 레이아웃 같은 것들만 담는다.

"어떤 기기에 무엇이 켜져 있는가"는 `host.toml`을 보면 알 수 있다.
"워크스테이션 환경이 무엇을 포함하는가"는 `workstation.toml`을 보면 알 수 있다.
`nhw check`를 돌리면 그 선언과 실제 옵션 목록이 일치하는지 검증된다.

**내가 사용하는 것을 내가 선언한다. 선언하지 않은 것은 켜지지 않는다.**
