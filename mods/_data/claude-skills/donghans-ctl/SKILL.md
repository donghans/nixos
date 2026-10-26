---
name: donghans-ctl
description: 이 환경의 ctl류 명령(observectl·procctl·hostres·donghans ctx/instr/secret 등)이 무엇을 하고 어떤 것이 `--json` 공통 봉투를 주는지 한곳에서 찾는 색인. 「어떤 ctl 을 써야 하나」「--json 출력 형식이 뭔가」「봉투」「종료 코드」「ctl 이 구조화 출력을 주나」를 판단하기 전에 먼저 읽는다. 각 도구의 상세 사용법은 가리키는 스킬을 읽는다.
---

# donghans-ctl — ctl 명령 색인과 `--json` 봉투

사람은 TUI 를 보고, LLM 세션은 ctl 을 쓴다. ctl 은 미려한 표보다 **알아듣기 쉬운 구조**가 중요하므로 `--json` 을 주고, 가능한 한 같은 봉투를 쓴다(정본 `mods/_data/_ctlkit/ctlkit.py`).

## 공통 봉투 (`--json`)
```
{"command": "top", "ok": true, "structured": true, "exit_code": 0,
 "data": {…}            # structured=true 일 때 구조화 결과
 "text": "…"            # structured=false 일 때 사람용 출력 그대로
 "notes": ["…"]         # 표 위에 괄호로 찍던 참고 문구
 "error": "…"}          # ok=false 일 때 사유 (data 가 함께 올 수 있다 — 예: 제외 목록)
```
- 종료 코드 = 봉투의 `exit_code`. 의미는 도구별(procctl: 0 성공 · 2 대상 없음 · 3 거부 · 4 전부 보호 · 5 일부 실패).
- `structured=false` 면 `text` 를 읽는다(그 명령은 아직 data 로 구조화되지 않았다).
- NaN·무한대는 `null`.

## 도구별
| 도구 | 하는 일 | `--json` | 먼저 읽을 스킬 |
|---|---|---|---|
| `observectl` | 성능·자원·전력 관측 기록 조회 | **공통 봉투**. 구조화(data): status·top·states·events·query·wakers·energy(explain 은 자체 --json). 나머지는 text 봉투 | `donghans-observe` |
| `procctl` | 프로세스 정리(plan → 사용자 확인 → apply → escalate) | **공통 봉투**(data 에 plan·groups 등). `log` 는 JSON 없음 | `donghans-procctl` |
| `hostres.py` | 가용 자원 스냅샷·판정 | 자체 JSON(봉투 아님) | `donghans-host-resources` |
| `donghans ctx …` | 지난 대화·사용량 조회 | 없음(텍스트) | `donghans-ctx` |
| `donghans instr`·`secret`·`handoff` | 프로젝트 지침·비밀 실행·인수인계 | 없음(텍스트) | `donghans-ctx` / `donghans-handoff` |
| `limitwatch.py` | 구독 한도 상태 | 자체 `--json` | `donghans-limit-watch` |

## 새 ctl 을 만들 때
`ctlkit.emit_json`·`Out`·`run_json` 을 쓴다(observectl 의 `run`, procctl 의 `emit`/`die` 가 예). 실패도 같은 봉투(ok=false + error + 같은 종료 코드)로 낸다. 설치본은 같은 디렉터리에 `ctlkit.py` 를 복사해야 import 된다(`mods/sys/services/observe.nix` 참고).
