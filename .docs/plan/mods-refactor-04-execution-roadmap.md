# 🚀 Execution Roadmap: Refactoring Process

본 문서는 리팩터링 과정에서 발생할 수 있는 코드 유실을 방지하고, 경로 변경에 따른 의존성 문제를 체계적으로 해결하기 위한 10단계 실행 로드맵을 정의합니다.

## 📋 리팩터링 실행 10단계

### 1. 영향 범위 분석 (Impact Analysis)
- 리팩터링 대상이 되는 모든 파일(`*.nix`, `*.sh`, `*.json` 등)을 탐색하고 목록을 확정합니다.
- `grep` 및 `find`를 사용하여 내부 참조 관계를 파악합니다.

### 2. 원본 보존 (Snapshot: before-refactor/)
- `before-refactor/` 디렉터리를 생성합니다.
- 확정된 대상 파일들을 수정 전 상태 그대로 `before-refactor/` 하위로 이동(Move)시켜 원본 스냅샷을 생성합니다.

### 3. 작업 공간 준비 (Workspace: working-refactor/)
- `working-refactor/` 디렉터리를 생성합니다.
- `before-refactor/`에 있는 파일들을 `working-refactor/`로 복사하여 분석 및 주석 작업을 위한 공간을 마련합니다.

### 4. 실행 환경 명시 (Runtime Context Annotation)
- `working-refactor/` 내의 모든 `.nix` 파일을 전수조사합니다.
- `imports = [ ... ]` 구문 바로 위에 다음 주석을 추가하여 빌드 시점의 맥락을 명시합니다.
  ```nix
  # [working-refactor] 해당 파일은 실제 /tmp/nixos-build/<경로> 로 이동 후 nhw에 의해 임시 경로에서 실행됩니다.
  ```

### 5. 코드 이력 추적 주석 추가 (Line-level Traceability)
- `working-refactor/` 내의 `.nix` 파일 내 주요 구문들에 대해 이동 전/후 경로를 주석으로 기록합니다.
  ```nix
  # [working-refactor] 해당 구문은 before-refactor/.../파일명.nix:Lnn-Lmm 라인에 있었음
  # [working-refactor] 해당 구문은 after-refactor/.../파일명.nix에 들어가야 함
  ```

### 6. 쉘 스크립트 경로 분석 (Script Path Mapping)
- `working-refactor/` 내의 `.sh` 파일들을 전수조사합니다.
- 하드코딩된 경로나 상대 경로가 기입된 곳에 리팩터링 후 변경될 경로를 주석으로 추가합니다.
  ```bash
  # [working-refactor] 해당 쉘 스크립트 경로는 리팩터링이 된다면 <경로> 로 바뀌어야 함.
  ```

### 7. 최종 결과물 생성 (Target: after-refactor/)
- `after-refactor/` 디렉터리를 생성합니다.
- `working-refactor/`에서 분석된 내용을 바탕으로 실제 리팩터링된 구조에 맞게 파일을 `after-refactor/` 내에 작성(Write)합니다.

### 8. 무결성 검증 (Integrity Check)
- `after-refactor/` 디렉터리의 전체 내용을 `before-refactor/`와 대조합니다.
- 누락된 설정 구문이나 로직이 없는지 전수 체크하여 리팩터링의 완전성을 보장합니다.

### 9. 시스템 적용 (Deployment)
- 검증이 완료된 `after-refactor/` 내의 파일들을 실제 프로젝트 루트(`~/nixos/`)의 해당 경로로 이동시킵니다.

### 10. 최종 빌드 검증 (Final Validation)
- `nhw check` 명령을 수행하여 안티패턴, 포맷팅, 빌드 무결성을 최종적으로 검증합니다.
- 오류 발생 시 로드맵의 주석 이력을 바탕으로 원인을 추적하고 수정합니다.
