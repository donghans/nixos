# mods/_tools — 실행되는 도구·앱과 시험

Nix 모듈(`mods/sys|gui|devel`)이 설치해 실행하는 도구(Python·쉘)와 그 시험을 둔다. 앱마다 폴더 하나이고, 설계·사용·주의는 **그 폴더의 README.md** 에 있다.
(`mods/_data/` 는 Nix 가 읽는 데이터 파일 — zsh 스크립트·CSS·패치·스킬 문서. 실행 코드는 여기.) 모든 시험: `mods/_tools/run-tests.sh`.

| 폴더 | 무엇 | 문서 |
|---|---|---|
| `observe/` | 관측(observectl)·usageui(실시간·시계열·호스트 비교) | `observe/README.md` |
| `procui/` | 프로세스 정리 TUI(procui)와 LLM 용 CLI(procctl) | `observe/README.md` 의 procui 절 |
| `llm-ctx/` | 여러 머신·프로젝트의 LLM 대화·사용량 공유 저장소(`donghans` 명령, ctxui) | `llm-ctx/README.md`, `llm-ctx/portability.md` |
| `llm-sessions/` | LLM 세션을 tmux 에서 돌리고 어디서든 이어 붙는 목록 UI(`llm-sessions`) | `llm-sessions/README.md` |
| `llm-usage/` | 5h·7d 한도 기록을 남기는 상태줄 스크립트(Claude Code 전용) | `llm-usage/README.md` |
| `notif/` | 알림 센터 | `notif/README.md` |
| `posture/` | 힌지 각도로 laptop/tent/tablet 판정하는 자세 허브 | `posture/README.md` |
| `extkbd/` | 외부 키보드가 있으면 내장 키보드를 끄는 감시 | `extkbd/README.md` |
| `display/` | 모니터 구성 CLI·TUI(displayctl·displayui) | `display/README.md` |
| `qa-desktop/` | 화면 확인용 QA 데스크톱 VM 제어 | `qa-desktop/README.md` |
| `media-bench/`·`office-fonts/` | 이미지·영상·오디오 프로그램 비교 측정 / 오피스 글꼴 별칭 | `media-bench/README.md` |
| `clipboard/`·`vkb/`·`touch-trace/`·`input-debug/`·`power-ab/`·`netdata/`·`hyprland-nested/` | 클립보드 UI·화상 키보드·터치 추적·키 입력 점검·전력 A/B·전력 리포트·중첩 Hyprland | 해당 폴더 코드의 머리말 주석 |
| `_lib/` | 앱들이 공유하는 라이브러리: `_uikit`(TUI 공통 틀)·`_ctlkit`(CLI 의 `--json` 봉투)·`_testkit`(시험 도구) | 각 파일 머리말 |
