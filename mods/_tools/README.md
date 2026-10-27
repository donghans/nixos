# mods/_tools — 실행되는 도구·앱과 시험

Nix 모듈(`mods/sys|gui|devel`)이 설치해 실행하는 도구(Python·쉘)와 그 시험을 둔다. **기능별 카테고리(`llm/`·`observe/`·`desktop/`·`services/`) 아래에 앱마다 폴더 하나**이고, 설계·사용·주의는 **그 폴더의 README.md** 에 있다.
- `mods/_data/` — Nix 가 읽는 데이터 파일(zsh 스크립트·CSS·스킬 문서 등). 실행 코드는 여기.
- `mods/_patches/` — 외부 소스에 적용하는 `.patch`(wofi·wvkbd).
- `mods/_experiments/` — Nix 가 설치하지 않고 수동으로만 쓰는 진단·실험 도구.
모든 시험: `mods/_tools/run-tests.sh`.

| 폴더 | 무엇 | 문서 |
|---|---|---|
| `llm/llm-ctx/` | 여러 머신·프로젝트의 LLM 대화·사용량 공유 저장소(`donghans` 명령, ctxui) | `llm/llm-ctx/README.md`, `llm/llm-ctx/portability.md` |
| `llm/llm-sessions/` | LLM 세션을 tmux 에서 돌리고 어디서든 이어 붙는 목록 UI(`llm-sessions`) | `llm/llm-sessions/README.md` |
| `llm/llm-usage/` | 5h·7d 한도 기록을 남기는 상태줄 스크립트(Claude Code 전용) | `llm/llm-usage/README.md` |
| `observe/observe/` | 관측(observectl)·usageui(실시간·시계열·호스트 비교), `ab/` 에 번갈아(ABAB) 측정 틀과 시나리오 | `observe/observe/README.md` |
| `observe/process-manager/` | 프로세스 정리 TUI(procui)와 LLM 용 CLI(procctl) | `observe/observe/README.md` 의 procui 절 |
| `observe/power-ab/` | 전력 A/B 시험 실행기(`power_ab.py`) | 코드 머리말 주석 |
| `observe/power-report/` | Netdata API 로 전력 그래프를 그리는 `power_report.py` | `_docs/content/how-to/monitoring.md` |
| `desktop/notification-center/` | 알림 센터 | `desktop/notification-center/README.md` |
| `desktop/posture/` | 힌지 각도로 laptop/tent/tablet 판정하는 자세 허브 | `desktop/posture/README.md` |
| `desktop/external-keyboard/` | 외부 키보드가 있으면 내장 키보드를 끄는 감시 | `desktop/external-keyboard/README.md` |
| `desktop/monitor-manager/` | 모니터 구성 CLI·TUI(displayctl·displayui) | `desktop/monitor-manager/README.md` |
| `desktop/clipboard/`·`desktop/virtual-keyboard/` | 클립보드 UI / 화상 키보드(wvkbd 패치는 `mods/_patches/wvkbd/`) | 코드 머리말 주석 |
| `desktop/office-font-alias/` | 오피스 글꼴 별칭(빌드 때 `office.nix` 가 실행) | 코드 머리말 주석 |
| `desktop/hwctl/` | 노트북 하드웨어 제어 쉘 스크립트(볼륨·밝기·덮개·터치 토글) | `desktop/hwctl/README.md` |
| `services/qa-desktop/` | 화면 확인용 QA 데스크톱 VM 제어 | `services/qa-desktop/README.md` |
| `services/tailpass/` | 외부 프로젝트(tailpass)의 `deploy/nix/*` 와 `.deb` 를 베낀 사본(`sync.sh`) | `services/tailpass/` 머리말 |
| `_lib/` | 앱들이 공유하는 라이브러리: `_uikit`(TUI 공통 틀)·`_ctlkit`(CLI 의 `--json` 봉투)·`_testkit`(시험 도구) | 각 파일 머리말 |
