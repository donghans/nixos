---
name: donghans-qa-desktop
description: incus VM `qa-desktop`(Ubuntu GNOME Wayland)에서 사용자와 같이 화면을 보며 headed 브라우저로 QA·화면 확인을 하거나, 여러 프로젝트의 QA 세션이 그 VM 을 공유할 때 따르는 절차. 「화면 확인」「qa-desktop」「headed 브라우저」「Flutter 웹 접근성 트리」「가상 데스크톱」「다른 QA 세션과 VM 공유」 같은 요청이나, ~/qa-playwright·run.sh·ws.py·snap.py 를 쓰려 할 때 먼저 읽는다. 접속·실행 방법, 프로젝트별 창 배치(Auto Move Windows), 사람 없이 화면 캡처·데스크톱 전환, 점유 알림 규칙, 승인 필요 작업, 복구(gdm3 재시작·스냅샷)를 담는다.
---

# donghans-qa-desktop — 화면 확인용 QA 데스크톱 (incus VM)

> 이 스킬은 사용자의 워크스테이션 전용이다(저장소에 추적되지 않음). 스킬 형식(SKILL.md)과 경로(`~/.claude/skills/`)는 Claude Code 기준이고 본문은 에이전트에 중립적으로 썼다(세션 간 메시지 도구처럼 에이전트 전용인 부분은 괄호로 표시하고 기본 수단을 따로 둔다). 설명·측정 근거·되돌리는 법은 `~/nixos/_docs/content/explanation/qa-desktop.md`.

## 언제 쓰나
- **쓴다**: 사용자와 같이 화면을 보는 headed 브라우저 확인, Flutter 웹처럼 접근성 트리가 필요한 확인.
- **안 쓴다**: headless 자동 E2E(전역 규칙은 호스트에 브라우저를 설치·실행하지 않고 Docker 에서 하는 것). 이 VM 은 호스트에 브라우저를 설치하지 않으므로 그 규칙의 취지와 충돌하지 않는다. 프로젝트가 headless 스크립트를 이 VM 에서 돌리는지는 그 프로젝트 QA 문서를 따른다(ToT 최근 라운드는 `headless:true` 이고 실행 위치는 이 스킬이 확정하지 않는다).

## 사전 점검 — 처음 쓰는 세션·호스트라면 접속 전에
이 스킬은 **이 워크스테이션에 qa-desktop VM 이 이미 있다**는 전제다. 아래를 순서대로 확인하고, **하나라도 어긋나면 임의로 만들거나 고치지 말고 사용자에게 알린다**(VM 생성·패키지·설정은 승인 필요 작업).
1. 호스트에 incus 가 있고 VM 이 있는가: `incus list ^qa-desktop$`(**`^…$` 로 정확 일치** — 이름만 쓰면 `qa-desktop-test` 같은 접두 일치 VM 까지 나온다) — `qa-desktop-ctl status` 가 있으면 그것을 쓴다. 없으면: 호스트 스위치가 꺼져 있으면(`qa-desktop` 도구가 없다) 이 호스트는 대상이 아니고, 스위치가 켜져 있는데 VM 이 없으면 사용자에게 알리고 **승인 후** `qa-desktop-ctl ensure`(없을 때만 만든다; 약 4~5분, 이미지 1.4GB).
2. 접속 키가 있는가: `ls ~/.ssh/qa_desktop_ed25519` — 없으면 사용자에게 키 위치를 묻는다(공개키는 VM 의 `qa` 계정 `authorized_keys` 에 있어야 한다. `ensure` 로 새로 만든 VM 은 키를 직접 만들어 넣는다).
3. VM 이 살아 있는가: `timeout 6 ssh -i ~/.ssh/qa_desktop_ed25519 qa@10.100.0.84 echo alive` — 상태가 RUNNING 인데 접속이 안 되면 아래 「복구」.
4. 내 프로젝트의 규칙이 있는가: 프로젝트의 `.claude/donghans-instructions.md` 「QA 할 때」 절에 창 이름(`<프로젝트>-qa`)·데스크톱 번호가 있는지. **없는 새 프로젝트면** 창 자동 배치 규칙이 없어 창이 지금 보고 있는 데스크톱에 뜬다(문제는 아님 — 규칙 추가는 아래 「화면 분리」의 절차를 사용자 승인 후).
5. 지금 다른 프로젝트가 쓰고 있는가: `python3 ~/.claude/skills/donghans-qa-desktop/scripts/occupy.py list`(스킬 폴더의 `scripts/`; 아래 「공유 규칙」).

## 접속·실행
- 접속: `ssh -i ~/.ssh/qa_desktop_ed25519 qa@10.100.0.84`(비밀번호 없음). 살아 있는지: `timeout 6 ssh … echo alive`.
- RUNNING 인데 ssh 가 `No route to host` → VM 크래시(원인 미확정, 조건은 `qa-desktop.md`). VM 안에서 `journalctl -b -1` 로 직전 로그를 본 뒤 호스트에서 `incus restart qa-desktop --force`. **`incus exec` 는 VM 에이전트가 없어 안 된다.**
- 실행: `~/qa-playwright/run.sh <스크립트.js>` — GUI 환경변수(Xwayland 인증 파일 등)를 매번 동적으로 잡는다. Playwright 1.63·node 22 를 **모든 프로젝트가 공유**한다.
- 이름 규칙: 스크립트 `~/qa-playwright/flow_<프로젝트>/`, 산출물 `~/qa-shots/<프로젝트>/`, 임시 `/tmp/<프로젝트>-*`, 변경 전 값 기록 `~/<프로젝트>-qa-state/`. VM 안에서 띄우는 정적 서버 포트도 프로젝트별로 나눈다(ToT 는 9873 을 쓴다 — 겹치지 않게 다른 번호를 고른다). 로그인 헬퍼 `~/qa-playwright/login.js` 는 ToT 전용이니 가져다 쓰지 말고 프로젝트별로 만든다.
- 다른 프로젝트의 디렉터리·`package.json`·`node_modules` 는 고치지 않는다. apt·npm 업그레이드 금지(필요하면 사용자와 상대 QA 세션 합의 후).
- **ssh 로 백그라운드 프로세스를 띄울 땐** `(cd <디렉터리>; setsid nohup <명령> > log 2>&1 < /dev/null &)` 형태로 한다. 표준 입출력을 물고 있으면 ssh 연결이 안 닫혀 명령이 멈춘다.
  흔한 실수: `cd … && setsid nohup … &` 는 `&&` 체인 전체가 백그라운드 서브셸이 되어 출력을 잡고 있으니 쓰지 않는다. 끝날 때까지 기다릴 땐 같은 ssh 안에서 `until grep -q DONE log; do sleep 2; done`.
- **창 유지 시간**: 창을 띄워 두고 `ws.py`·`snap.py` 로 위치까지 확인하려면 60초는 빠듯하다(ssh 왕복·scp 에 시간이 든다). 스크립트의 유지 시간을 환경변수(`HOLD_SEC`, 기본 120 권장)로 받게 만든다.
- 호스트 쉘이 zsh 면 scp 대상은 `${H}:경로` 로 쓴다(`$H:경로` 는 `:경로` 가 zsh 수식어로 해석돼 깨진다).
- 스크린샷은 **페이지 단위** `page.screenshot` 을 쓴다. WebGL 캔버스를 `locator.screenshot()` 으로 찍으면 이후 캔버스가 비는 현상을 봤다(원인 미확인).

## 화면 분리 (가상 데스크톱 + 창 자동 배치)
- 사용자는 가상 데스크톱을 오가며 본다. 창은 Chromium `--class=<프로젝트>-qa`(+ `--ozone-platform=wayland --start-maximized`)로 띄운다.
- GNOME 확장 **Auto Move Windows** 가 `~/.local/share/applications/<프로젝트>-qa.desktop`(`StartupWMClass=<프로젝트>-qa`)을 규칙 `<프로젝트>-qa.desktop:<데스크톱 번호>` 로 보낸다(`gsettings get|set org.gnome.shell.extensions.auto-move-windows application-list`, 번호는 1부터).
- 현재 규칙: `genple-qa.desktop:2` 하나뿐. ToT 는 규칙이 없어 **지금 보고 있는 데스크톱에 뜬다**(그대로 둔다). 새 프로젝트는 기존 항목을 유지한 채 추가한다. `focus-new-windows`(`smart`) 는 바꾸지 않는다(ToT 영향 미확인).
- 이 확장은 Wayland 라서 **로그아웃·재로그인 후에야** 새로 인식된다.

## 사람 없이 확인하기 (사용자에게 데스크톱 번호를 묻지 않는다)
데스크톱 번호는 화면에 안 보인다. 아래 도구로 직접 확인한다. 도구는 이 스킬의 `scripts/` 에 있다. **`qa-desktop-ctl` 로 새로 만든 VM 에는 이미 `~/qa-tools/ws.py`·`snap.py` 가 있다**(직접 만든 기존 VM 은 scp 로 `/tmp/<프로젝트>-qa/` 에 복사). ssh 로 실행할 때는 `XDG_RUNTIME_DIR=/run/user/1000 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus` 가 필요하다.
- `ws.py right|left|home|escape` — 데스크톱 전환(Mutter RemoteDesktop 가상 키 입력). `home` = 데스크톱 1 로 강제(← 를 8번) → 「현재 데스크톱=1」이 확정되므로 「창이 보이면 1 에 있다」로 판정할 수 있다. `escape` = 열려 있는 GNOME 개요(Activities) 닫기.
  **Super 키를 쓰지 않는다**: Super+Home 으로 보냈을 때 캡처가 실제 데스크톱이 아니라 개요(검색창·썸네일) 화면이던 적이 있다(2026-10-23, genple QA 시험 2회·직접 재현 1회; ToT 시험·추가 재현 4회는 정상이라 **조건 미확정인 간헐 현상**). Super 를 쓰지 않으면 가능성 자체가 없어서 `home` 을 ← 반복으로 바꿨다. 캡처가 개요 모양이면 `ws.py escape` 후 다시 찍는다.
- 가상 데스크톱은 **동적**이다: 창이 있는 데스크톱 + 끝에 빈 하나만 존재한다(창이 없을 땐 2개, genple-qa 창이 2번에 있으면 3개; 설정값 `num-workspaces=4` 와 다르게 동작함을 측정으로 확인). 맨 끝에서 `right` 를 더 눌러도 늘거나 순환하지 않는다.
- `snap.py <출력.png>` — 현재 **보이는** 데스크톱 전체 캡처(ScreenCast+PipeWire+GStreamer). 찍는 동안 상단바에 화면 공유 표시가 잠깐 뜬다. `org.gnome.Shell.Screenshot`·`GetWindows` 는 막혀 있어 못 쓴다.
- 비가시 데스크톱 렌더링은 DOM 기준으로 정상(프레임·스크린샷·클릭, 픽셀 최신성까지 확인). **WebGL·CanvasKit 은 미검증**.

## 공유 규칙 (여러 QA 세션이 VM 하나를 쓴다)
- **점유 알림(에이전트 종류와 무관한 기본 수단)**: 쓰기 전에 `occupy.py list`(위 경로의 같은 폴더) 로 확인하고 `occupy.py start <프로젝트> <예상분> [메모]` 로 시작을 적고, 끝나면 `occupy.py end <프로젝트>`. VM 안의 작은 파일(`/tmp/qa-desktop-occupancy/`)이라 메시지 도구가 없는 에이전트도 같은 정보를 읽고 쓴다. 락이 아니라 **알림**이다(강제하지 않는다) — 다른 프로젝트가 점유 중이거나 chrome 이 떠 있으면 경고하고 종료 코드 1 을 낸다.
- **세션 간 메시지 도구가 있으면 같이 쓴다**(Claude Code: 세션은 `ListAgents`, 알림은 `SendMessage`): 상대 QA 세션에 시작과 **예상 시간**을 직접 알리면 더 빠르다. 응답이 없고 오래 걸리면 `pgrep chrome` 으로 사용 중인지 본 뒤 진행한다. 락 파일은 두지 않는다.
- 끝나면 chrome 이 남지 않았는지 확인한다. VM 은 4CPU/8GiB, 호스트 여유 메모리가 작아 다른 VM 과 동시에 무겁게 돌리지 않는다.
- 상대 세션의 사전 수락 범위는 그 세션 사용자의 것이다 — 약속은 시작 알림까지만 하고 점유 일정을 대신 약속하지 않는다.

## 사용자 승인이 필요한 것 (승인 없이 하지 않는다)
VM 설정·`gsettings` 변경, apt 설치·업그레이드, 재로그인·재부팅, 스냅샷 복원, 확장 설치·변경.
- **화면 잠금은 항상 유지**: `lock-enabled false`, `idle-delay 0`(계정에 비밀번호가 없어 잠기면 GUI 로 못 푼다). 풀렸다면 `loginctl unlock-session 1` + dbus `org.gnome.ScreenSaver.SetActive false`.
- 위험한 변경 직전: `incus snapshot create qa-desktop <이름>`(기존: `genie-test-base`, `pre-2604`, `pre-apt-20261022`, `pre-automove-20261023`). 변경 전 값과 **되돌리는 명령**을 `~/<프로젝트>-qa-state/` 에 남기고, 변경 후 상대 QA 세션에 smoke 를 요청한다.
- **재로그인**(`gnome-session-quit --logout --no-prompt`) 뒤에는 자동 로그인이 적용되지 않아 greeter 에서 멈춘다 → ssh 로 `sudo systemctl restart gdm3`. 그다음 `lock-enabled`·`run.sh` 의 Xwayland 인증 파일·자동 로그인을 확인한다. 자동 로그인은 부팅 직후에만 적용된다.
