# Mods Framework Refactoring Checkpoint

## 📅 날짜: 2026-04-07
## 🎯 목표: Phase 2 - Core Architecture & Domain Mapping 완수

---

## 1. 🚀 현재까지의 진행 상황 (Progress)

### ✅ 완료된 사항
1.  **SSOT(Single Source of Truth) 체계 구축**:
    *   `core/lib/workspace-options.nix` 신설: `config.workspace` 및 `config.mods` 옵션 트리 선언 완료.
    *   `core/lib/builders.nix` 및 `core/flake.nix` 개편: 모든 모듈에 `config.workspace` 및 `isNixOS` 플래그 주입 로직 적용.
2.  **`mods/sys` 도메인 격리**:
    *   `fonts`, `vfs`, `nfd`, `services(docker, bluetooth, tailscale)` 기능을 독립 모듈로 분리 및 `mkIf` 기반 Opt-in 구조 적용 완료.
3.  **물리적 디렉터리 재편**:
    *   `mods/gui/apps`, `mods/gui/utils`, `mods/devel/toolchains` 등 논리적 역할에 따른 디렉터리 구조 생성.
    *   정적 데이터(`devbox` JSON 등)를 `mods/_data`로 이동시켜 코드와 데이터 분리.

---

## 2. ⚠️ 발견된 문제점 (Current Issues)

### ❌ 구문 오류 (Syntax Errors)
*   **Host 설정 파일 파손**: `sed` 명령어를 통한 `config = { ... }` 블록 평탄화 과정에서 닫는 중괄호(`}`)가 누락되거나 잘못 제거되어 `nhw check` 시 `unexpected end of file` 에러 발생.
*   **중복 람다 선언 (Nested Lambdas)**: `refactor.py` 스크립트가 기존 Nix 파일의 인자 선언(`{pkgs, ...}:`)을 고려하지 않고 외부를 다시 `{config, lib, ...}:`로 감싸면서 `{config, ...}: { {pkgs, ...}: { ... } }`와 같은 잘못된 구조 생성.
*   **Unused Arguments**: `deadnix` 검사 결과, 다수의 모듈에서 사용되지 않는 `pkgs` 또는 `isNixOS` 인자가 선언되어 있어 경고 발생.

### 🏗️ 구조적 미완성
*   **GUI/Devel 잔여 로직**: 파일 분리는 되었으나, 내부 코드가 새로운 `config.mods` 옵션 체계에 맞게 완전히 정제되지 않음.
*   **ISO 설정**: `core/iso.nix` 등에서 기존 경로 참조가 남아있거나 새로운 옵션 체계가 완전히 반영되지 않음.

---

## 3. 🛠️ 복구 및 완수 계획 (Recovery & Completion Plan)

### Step 1: Host 파일 긴급 복구
*   `hosts/` 하위의 `configuration.nix` 및 `home.nix` 파일들을 전수 조사하여 문법을 올바르게 수정 (명시적 `mods.*.enable = true;` 선언 포함).

### Step 2: 모듈 구문 정제 (Lambda Fix)
*   `mods/gui` 및 `mods/devel` 하위의 모든 신규 모듈을 검토하여 중복된 함수 선언을 제거하고 단일 표준 포맷(`{ config, lib, pkgs, ... }:`)으로 통일.

### Step 3: 도메인 기능 완결
*   `gui/core` 활성화 시 `sys/fonts`, `sys/vfs`가 자동으로 트리거되는 로직 재검증.
*   `devel/toolchains` 및 `jetbrains` 모듈들의 부수 효과(ADB, Firewall)가 올바르게 작동하는지 확인.

### Step 4: 최종 검증
*   `nhw check`를 통해 경고 제로(Zero Warnings) 상태 달성.
*   `nhw os switch` / `nhw home switch` 테스트 (드라이 런).

---

## 4. 💡 의도 (Intentions Recap)
본 작업의 핵심은 "설정의 가시성 확보"입니다. 사용자가 `hosts/`의 짧은 설정 파일만 보고도 "이 기기에는 어떤 기능(Mods)들이 켜져 있는가"를 한눈에 파악할 수 있게 하며, 모든 데이터는 `config.workspace`를 통해 일관되게 접근하도록 만드는 것이 최종 목표입니다.
