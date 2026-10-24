# `claude-limit-watch` 가 `PATH` 에 안 잡히던 문제 — 조사 기록과 해결(스킬 이전)

작성 2026-10-24, 저장소 stable `9985afe` 기준, 호스트 `beelink-ser7-co`. §1~§5 는 조사 당시의 기록이고, 해결은 §5-1 에 있다(그 뒤 `claude-limit-watch` 는 `donghans-limit-watch` 스킬로 대체되어 사라졌다).

## 1. 한 줄 요약
- 큰 작업 직전에 `claude-limit-watch <접두>` 를 Monitor 로 걸라는 전역 지침이 있는데, 이름만으로 실행하면 이 호스트에서 `command not found`(종료 코드 127)가 난다. 파일은 `~/.local/bin/claude-limit-watch` 로 **설치돼 있고**, 그 디렉터리가 `PATH` 에 없을 뿐이다.
- 전체 경로(`~/.local/bin/claude-limit-watch`)로 실행하면 정상 동작한다. 다른 세션들도 같은 증상을 겪고 전체 경로로 우회해 왔다.
- 감시기는 시작할 때 과거 기록을 전부 재생해 "급증" 알림을 쏟아내는데, 이것은 설계된 동작이라 무시하면 된다(§3-3).

## 2. 용어
- **`claude-limit-watch`**: Claude Code 구독의 5시간·7일 사용 한도(`limits.jsonl`)를 지켜보다가 사용량이 튀면 한 줄을 출력하는 파이썬 스크립트. 출력 한 줄이 곧 알림이라 Monitor 도구로 걸어 둔다. 소스 `mods/_data/claude-usage/claude-limit-watch`.
- **Monitor**: Claude Code 의 도구. 백그라운드 명령의 표준출력 한 줄마다 대화에 알림을 보낸다.
- **home-manager(`home.file`)**: 이 저장소가 NixOS 사용자 환경에 파일·링크를 만드는 방식. `nixup` 으로 배포하면 반영된다.
- **세션 ID 접두**: `echo $CLAUDE_CODE_SESSION_ID` 의 앞 8자. 감시기의 필수 인자(`--own` 일 때만 필터로 쓰이고, 기본은 모든 세션의 기록을 본다).
- **ctx**: 여러 머신·세션의 대화를 모은 공유 저장소(`donghans ctx` 명령). 이 문서가 인용하는 다른 세션 대화는 모두 여기서 조회했다.

## 3. 일어난 일 (확인된 사실)

### 3-1. 설치돼 있으나 `PATH` 에 없다
| 사실 | 등급 | 근거 |
|---|---|---|
| 지침: 앞 8자로 `claude-limit-watch <접두>` 를 Monitor 로 실행 | 직접확인 | `mods/devel/apps/llm-cli.nix:302` — `` `claude-limit-watch <접두>` 를 Monitor 로 실행합니다(5시간 한도가 10분 내 +5포인트 오르거나 50/70/80/90% 도달 시 알림). `` (전역 `~/.claude/CLAUDE.md` 의 같은 내용을 생성하는 줄) |
| 설치: `home.file.".local/bin/claude-limit-watch"` 로 링크 생성 | 직접확인 | `mods/devel/apps/llm-cli.nix:368-372` |
| 링크가 실제로 있다 | 직접확인 | `ls -la ~/.local/bin` → `claude-limit-watch -> /nix/store/…-home-manager-files/.local/bin/claude-limit-watch`, 시각 2026-10-24 12:41 |
| 이름만으로 실행하면 127 | 직접확인 | Monitor 로 `claude-limit-watch 1b4a8bc2` 실행 → "failed (exit 127)" |
| 이 세션의 셸 `PATH` 에 `~/.local/bin` 없음 | 직접확인 | `echo $PATH` 출력 항목 중 없음. 새 `zsh -ic`·`zsh -lc` 도 같음(단, 이 둘은 현재 프로세스의 환경을 물려받아 "새 로그인"의 증거는 못 됨) |
| `env -i HOME=$HOME USER=$USER zsh -lic` 에서도 `command -v claude-limit-watch` 가 비어 있음 | 직접확인 | 출력 없음. `PATH` 를 찍으니 `~/.nix-profile/bin` 은 있고 `local/bin` 은 없음. `env -i` 는 로그인 때 로드되던 변수도 지우므로 **완전한 증거는 아님** |
| `~/.zshenv`·`~/.zshrc`(둘 다 home-manager 생성, store 링크)에 `~/.local/bin` 을 넣는 줄이 없음 | 직접확인 | `rg -n "PATH" ~/.zshenv ~/.zshrc` → `.zshrc:105-126` 의 `_ZSH_BASE_PATH` 관련 줄뿐. `~/.zprofile` 은 없음 |
| 저장소의 `.nix` 중 `.local/bin` 을 다루는 파일은 `llm-cli.nix` 하나 | 직접확인 | `rg -l "\.local/bin" ~/nixos --glob '*.nix'` (링크만 만들고 `PATH` 에는 넣지 않음). `home.sessionPath` 를 쓰는 곳은 찾지 못함(첫 grep 이 zsh glob 오류로 실패해, `--glob` 로 다시 한 `rg -ln "sessionPath"` 는 `.nix` 결과 없음) |
| 이 세션의 터미널은 링크 생성보다 이전에 열렸다 | 직접확인 | 프로세스 조상: Hyprland(10/14) → kitty(10/23 17:25) → zsh(17:25) → claude(10/23 17:27). tmux 아님(`TMUX`·`STY` 비어 있음) |
| 이 kitty 에서 Ctrl+Shift+T 로 연 새 탭, 그리고 워크스페이스 4 에 띄운 새 kitty 에서도 `command -v claude-limit-watch` 결과가 비어 있음 | 직접확인 | 결과를 `~/.cache/clw.txt` 로 리다이렉트해 크기 0 확인(리다이렉트는 명령이 실패해도 파일을 만든다). 두 터미널 모두 Hyprland(10/14 시작)가 만든 프로세스의 자식이라 **오래된 환경을 물려받았을 수 있음** |
| 사용자는 Ctrl+Shift+T 새 탭은 수동으로 해 봤을 때 "제대로 된다"고 말했다 | 사용자 진술 | 재현하지 못함. 위 표의 결과와 어긋나므로 **미해결 불일치**다 |

**확정하지 못한 것**: 완전히 새로 로그인한 환경(재로그인 또는 재부팅 뒤)에서도 `PATH` 에 안 들어가는지. 설정 파일에 넣는 줄이 없다는 것까지가 확정이다.

### 3-2. 다른 세션도 같은 증상
ctx 조회(`donghans ctx search "claude-limit-watch"`, `--role user|assistant`) 결과, 요지(원문 아님):
- 세션 `670ee995`(저장소 BITSTEP-IT/ToT, 2026-10-24 04:16): "처음에는 `PATH` 에 없어 실패했고, `python3 ~/.local/bin/claude-limit-watch` 로 다시 걸었습니다" — 원인 조사 없이 우회. **직접확인**(ctx 조회)
- 세션 `9fbe65e3`(저장소 genple, 2026-10-23 06:38)의 사용자 프롬프트에 전체 경로 `~/.local/bin/claude-limit-watch <첫 8자>` 와 "시작 때 이력을 재생해 소음이 난다"는 주의가 이미 적혀 있다. **직접확인**(ctx 조회, 인용은 앞부분이 잘려 요지만)
- 세션 `6d08622a`(이 저장소, 2026-10-23 13:02)는 "`claude-limit-watch` 가 이 머신에 없어서 감시를 걸지 못했다"고 보고했고, 이것이 인수인계 문서(`HANDOFF-6d08622a-….md` §5, 저장소 밖 로컬 파일)의 "이 호스트에 없다(설치하지 않음)" 문장이 되었다. 그 시점에 링크가 실제로 없었는지, 같은 `PATH` 문제를 "없다"로 잘못 판단했는지는 **미확인**. 이 세션(1b4a8bc2)은 그 문장을 재확인 없이 믿고 한 번 `command -v` 만 돌린 뒤 "없다"고 말했다가 정정했다.

### 3-3. 시작 때의 "급증" 알림은 재생이다
- 감시기는 `limits.jsonl` 을 처음부터(`pos = 0`) 읽고, 읽은 줄마다 "지금 시각"으로 윈도에 넣는다. 과거 기록이 한꺼번에 급증으로 판정된다. **직접확인**(소스 읽음: `claude-limit-watch` 의 `pos = 0`·`f.seek(pos)` 루프, `hist.append((now, f5))`).
- 이 세션에서 시작 직후 "5h 0%→100%", "주간 2%→87%", 서로 다른 세션 10여 개가 섞인 알림이 쏟아졌고, 같은 시각 사용량 스냅샷(`resume.py`)은 5h 약 42%·7d 약 24% 였다. 즉 현재와 어긋난 값이라 재생으로 판단했다. **직접확인**(두 값을 대조)
- 그 뒤의 알림(예: "34%→42%")은 스냅샷과 맞는 실제 값이었다.

## 4. 이 문서가 다루지 않은 것
- 완전한 새 로그인 환경의 `PATH`. 다른 호스트(노트북 `msi-summit-me` 등)에서도 같은지.
- `~/.local/bin` 에 있는 다른 항목(`claude-usage-statusline`)의 호출 방식. 상태 표시줄은 Claude Code 설정이 전체 경로로 부르는지 확인하지 않았다.
- 사용자가 말한 "수동으로 해 보면 제대로 된다"의 정확한 상황(어느 터미널·어느 명령).

## 5. 선택지 (아직 아무것도 하지 않음 — 사용자 결정 대기)
| 선택지 | 내용 | 비고 |
|---|---|---|
| A. `PATH` 에 추가 | `mods/devel/apps/llm-cli.nix` 에 `home.sessionPath = [ "$HOME/.local/bin" ];` 추가 후 `nixup` | 다음 로그인부터 반영. 설정 변경이라 `nixup` 필요. 이 선택은 `PATH` 를 쓰는 다른 도구에도 영향 |
| B. 지침을 전체 경로로 | `llm-cli.nix:302` 의 `claude-limit-watch <접두>` 를 `~/.local/bin/claude-limit-watch <접두>` 로 바꾸고 재배포 | `PATH` 와 무관하게 동작. 지침 문구만 바뀜 |
| C. 현상 유지 | 세션마다 전체 경로로 우회 | 지금처럼 실패 한 번을 거친다 |

추천: A 를 하되, 효과를 확인할 새 로그인이 필요하므로 B 를 같이 하면 `PATH` 에 의존하지 않는다(추정이며 사용자 결정).

## 5-1. 결과 (2026-10-24)
PATH 문제를 지침 문구로 우회하는 대신 도구 자체를 **스킬로 옮겨** 없앴다.
- `claude-limit-watch`(`~/.local/bin`) 를 폐기하고 `donghans-limit-watch` 스킬(`scripts/limitwatch.py`)로 대체했다. 스킬은 `python3 -I ~/.claude/skills/…` 로 부르므로 `PATH` 에 의존하지 않는다. 선택지 A(`home.sessionPath`)는 하지 않았다(uwsm 로그인에서는 닿지 않을 수 있음, `mods/gui/base/core.ui.cursor.nix:36` 주석과 같은 이유).
- §3-3 의 재생 소음도 함께 고쳤다: 시작 때 파일 끝부터 읽고 현재 상태 한 줄만 내며, 윈도는 레코드의 `ts`, 창 리셋은 `resets_at` 로 판정한다(예전엔 읽은 시각을 "지금"으로 넣어 과거 전체가 급증으로 판정됐고 `fired` 가 창 리셋 뒤에도 남았다).
- `status` 서브커맨드 추가: 현재 5h/7d·최근 증가·비용 상위 세션을 한 번 읽는다. 지침은 「큰 작업 직전 `status`, 오래 걸리면 `watch`」로 바뀌었다.
- 시험은 합성 `limits.jsonl` 로 했다(재생 없음·급증·수준·창 리셋 초기화). 실제 Monitor 로 걸어 본 시험은 배포 뒤 새 세션에서 확인할 일이다.

## 6. 다음 세션이 조심할 것
- 인수인계 문서의 "이 호스트에 없다" 문장은 **틀렸을 가능성**이 높다(§3-1). 재확인 없이 따르지 말 것. 확인은 `ls -la ~/.local/bin`.
- 시작 직후 알림이 쏟아져도 놀라지 말고 사용량 스냅샷과 대조할 것(§3-3).
- 이 조사 과정에서 "새 터미널에 키를 보내 확인"한 시도가 있었다(자동 모드가 한 번 막았고, 사용자 지시로 한 번 허용). 같은 방식은 권하지 않는다 — 설정 파일을 읽거나 사용자가 직접 새 터미널에서 `echo $PATH` 를 보는 편이 안전하다.
