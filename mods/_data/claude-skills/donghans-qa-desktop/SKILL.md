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
- 비가시 데스크톱 렌더링은 DOM 기준으로 정상(프레임·스크린샷·클릭, 픽셀 최신성까지 확인). **CanvasKit(Flutter 웹)은 숨긴 채 입력·페이지 캡처가 정상**(ToT QA 2026-10-23: 숨김 전후 캡처 바이트 동일, rAF 보임/숨김 120/121; 이 VM 의 swiftshader 소프트웨어 렌더 한정). 일반 WebGL 캔버스는 `locator.screenshot()` 뒤에 비는 현상이 있다(`page.screenshot` 사용). 프로젝트 화면의 WebGL 은 프로젝트별로 확인.
- **숨긴 창 조작 규칙(ToT QA 실측)**: `locator.click()`·`pressSequentially`(클릭 포함)는 숨긴 창을 보이는 데스크톱으로 **되돌린다**. `page.screenshot`·`evaluate`·`focus()`·`dispatchEvent('click')`·`keyboard.type` 은 숨김이 유지된다. 그러므로 ① 대부분의 QA 는 숨김에 의존하지 말고(숨김 시험은 렌더 검증처럼 꼭 필요할 때만), ② 숨긴 채 조작하는 시험은 클릭 없는 입력을 쓰며, ③ **단계마다 `snap.py` 로 상태(창이 보이는지·개요인지)를 확인해 어긋나면 그 단계 결과를 폐기하고 재시도**한다(사용자가 데스크톱을 직접 전환한 경우와 도구 원인을 함께 걸러낸다). ④ `ws.py home`/`right` 직후 캡처가 개요(Overview)로 나오는 일이 ToT 에서도 여러 번 있었다(조건 미확정) — 직후 `escape` 를 붙이고, 캡처가 개요인지 늘 눈으로 확인한다.
- **창을 새로 띄우는 순간은 사용자의 화면을 끌어온다**(ToT QA 실측 2회): 사용자가 데스크톱 1 을 보고 있어도 전용 데스크톱에 새 headed 창이 뜨면 보던 화면이 그 데스크톱으로 바뀐다(클릭의 창 활성화와 같은 계열로 보이며 원인 미확정). 완화: 창은 시험 시작 때 한 번만 띄워 재사용하고, 시험 중 새 창·headed `newContext` 생성을 줄이며, 시작 전에 사용자에게 알린다. 근본 해소(새 창 활성화 억제 설정)는 VM 설정 변경이라 사용자 승인 사안.
- **입력은 비우고 시작**: 숨긴 채 클릭 없는 입력(`focus`+`keyboard.type`)을 쓰면 Flutter 같은 캔버스 앱의 비밀번호 칸에서 앞 글자가 빠지는 일이 있었다(9자 중 8자, 재시도에서 재현 안 됨). 입력 전에 Ctrl+A+Backspace 로 비우고 입력한 뒤 길이·마스킹 표시로 확인하는 것을 표준으로 한다.
- **프로젝트별 전용 데스크톱**: 프로젝트마다 Auto Move 규칙(`<프로젝트>-qa.desktop:<번호>` + Chromium `--class=<프로젝트>-qa`)을 두면 시험 창이 항상 자기 데스크톱에 있어, 사용자가 어디를 보든 시험은 데스크톱 전환 없이 진행되고 사용자는 원할 때 그 데스크톱으로 가서 본다. 클릭이 창을 끌어오므로 위 숨긴 창 조작 규칙과 함께 지킬 때만 유효하다. 규칙 추가는 `decl.projects`(qa-desktop.nix) → `nixup home` → 사용자 승인 후 `qa-desktop-ctl provision`(GDM 을 재시작하므로 다른 세션이 점유 중이 아닐 때).

## 여러 계정을 쓰는 시험 (다계정·동시성)
- **동시성(같은 대상에 N 개 동시 요청)은 UI 가 아니라 호스트에서 API 로 돌린다**(`donghans-qa` §동시성·레인 규칙). VM 의 브라우저는 UI 가 꼭 필요한 시험에만 쓴다 — ToT 의 기존 기록도 동시성은 전부 호스트 API 병렬이었고 UI 다계정은 한 스크립트 안에서 계정마다 `newContext` 를 순차로 만든 것뿐이었다(동시에 여러 창을 열어 둔 사례는 없음, 2026-10-23 확인).
- **UI 에서 여러 계정이 필요하면 브라우저 한 개 + 계정마다 `browser.newContext()`**: 쿠키·스토리지가 컨텍스트별로 격리되어 계정 간 섞이지 않고, 프로필 디렉터리·chrome 프로세스를 늘리지 않아 4CPU/8GiB VM 에 가장 가볍다. 계정마다 chrome 을 따로 띄우거나 `--user-data-dir` 을 나누는 것은 로그인 상태 파일 시험처럼 꼭 필요할 때만.
- **창 구분**: Auto Move 규칙은 `--class=<프로젝트>-qa` 하나라 한 프로젝트의 창은 모두 같은 전용 데스크톱에 뜬다. 사람이 볼 필요가 없으면 `headless: true`(점유도 `--shared`), 사람이 같이 봐야 하면 보여줄 계정 1~2개만 headed 로 하고 나머지는 headless 로 둔다. 창이 겹치면 `viewport`·창 위치 인자(`--window-position`)로 나눈다.
- **UI 동시 로그인 시험이 필요하면**: 서로 다른 계정이 같은 자원(기사 수·같은 운행 등)을 건드리므로 `donghans-qa` 규칙대로 계정·대상을 레인 전용으로 먼저 확보하고, 컨텍스트를 `Promise.all` 로 같이 움직이되 입력은 클릭 없는 경로(`focus`·`dispatchEvent`·`keyboard.type`)를 우선한다. 컨텍스트 수 상한은 아직 측정한 적이 없다 — 처음엔 2~3개로 시작해 CPU(`top`)와 응답 시간을 기록하고 이 절에 실측값을 추가한다.

## 공유 규칙 (여러 QA 세션이 VM 하나를 쓴다)
- **누가 무엇을 하나**: 프로젝트마다 QA 세션이 있고, 그 프로젝트의 수정(개발) 세션은 자기 QA 세션에 요청만 한다. **QA 세션끼리의 조정은 개발 세션·사람 중재 없이 이 절의 규칙(점유 알림·전용 데스크톱)만으로 끝나야 한다.** 개발 세션이 다른 프로젝트 QA 세션을 직접 지휘하지 않는다. 도구·환경 자체(VM 선언·스킬·`occupy.py`)를 바꾸는 것은 워크스테이션(~/nixos) 세션의 일이다.
- **충돌 지점과 해소**(2026-10-23 실측으로 확인): ① 동시 사용 → `occupy.py start` 가 양보하고 `--wait` 로 순번을 기다린다(VM 은 한 번에 한 프로젝트가 쓰는 직렬 사용이 기본). ② 창 배치 → 프로젝트별 전용 데스크톱(Auto Move 규칙)이라 서로의 창을 끌어오지 않는다. ③ 화면 캡처·전환(`snap.py`·`ws.py`)은 「지금 보이는 데스크톱」 하나뿐이라 보이는 화면이 필요한 세션은 **배타 점유**(기본 `start`)로 독점한다. 반대로 전환·`snap`·클릭 계열 입력 없이 `page` 기반 캡처만 쓰는 시험은 **`start … --shared`** 로 선언해 다른 공유 점유와 **동시에** 돌릴 수 있다(각자 전용 데스크톱; Playwright 는 숨긴 창도 조작·캡처한다). 공유와 배타는 서로 양보한다. 동시에 돌리면 VM 은 4CPU/8GiB 라 느려질 수 있다. ④ 재프로비저닝(GDM 재시작)은 모든 창을 닫는다 → 점유가 없을 때, 사용자 승인 후에만.
- **점유 알림(에이전트 종류와 무관한 기본 수단)**: 쓰기 전에 `occupy.py start <프로젝트> <예상분> [메모]`(스킬 폴더 `scripts/`), 끝나면 `occupy.py end <프로젝트>`, 현황은 `occupy.py list`. VM 안의 작은 파일(`/tmp/qa-desktop-occupancy/`)이라 메시지 도구가 없는 에이전트도 같은 정보를 읽고 쓴다. **`start` 는 「기록 후 확인」이다: 다른 프로젝트가 점유 중이거나 chrome 이 떠 있으면 내 기록을 지우고 양보하며 종료 코드 1** — 그때는 VM 을 쓰지 말고 `start … --wait <분>` 으로 빌 때까지 기다린다(낡았고 chrome 도 없는 기록은 자동 정리)(`--force` 는 사용자 지시가 있을 때만). `list` 만 보고 시작하지 말 것: `list` 와 `start` 사이에 상대가 시작할 수 있다(실제로 겹칠 뻔했다).
- **세션 간 메시지 도구가 있으면 같이 쓴다**(Claude Code: 세션은 `ListAgents`, 알림은 `SendMessage`): 상대 QA 세션에 시작과 **예상 시간**을 직접 알리면 더 빠르다. 응답이 없고 오래 걸리면 `pgrep chrome` 으로 사용 중인지 본 뒤 진행한다. 락 파일은 두지 않는다.
- **chrome 정리는 자기 것만**: 공유 모드에서는 상대 프로젝트의 chrome 이 같이 떠 있다. `pkill chrome`·`killall chrome`·`pkill -f chrom` 같은 일괄 종료는 **상대 창을 죽인다**(2026-10-23 동시 실행 시험에서 ToT 브라우저가 시작 2초 뒤 닫힘 — genple 쪽 정리 시각과 겹쳐 의심, 미확정이나 구조적으로 가능). 종료는 **내가 띄운 브라우저 핸들(`browser.close()`)·내 PID·내 `--user-data-dir`/`--class=<프로젝트>-qa` 로 좁힌** 명령으로만 한다(`pkill -f` 는 자기 셸도 죽일 수 있으니 PID 로 지정). 시작 전 「chrome 이 남아 있으니 정리」도 다른 프로젝트 점유가 없을 때(`occupy.py list` 가 비었을 때)만 한다.
- 끝나면 **내** chrome 이 남지 않았는지 확인한다(다른 프로젝트 점유 중이면 전체 chrome 수가 0 이 아니어도 정상). VM 은 4CPU/8GiB, 호스트 여유 메모리가 작아 다른 VM 과 동시에 무겁게 돌리지 않는다.
- 상대 세션의 사전 수락 범위는 그 세션 사용자의 것이다 — 약속은 시작 알림까지만 하고 점유 일정을 대신 약속하지 않는다.

## 사용자 승인이 필요한 것 (승인 없이 하지 않는다)
VM 설정·`gsettings` 변경, apt 설치·업그레이드, 재로그인·재부팅, 스냅샷 복원, 확장 설치·변경.
- **화면 잠금은 항상 유지**: `lock-enabled false`, `idle-delay 0`(계정에 비밀번호가 없어 잠기면 GUI 로 못 푼다). 풀렸다면 `loginctl unlock-session 1` + dbus `org.gnome.ScreenSaver.SetActive false`.
- 위험한 변경 직전: `incus snapshot create qa-desktop <이름>`(기존: `genie-test-base`, `pre-2604`, `pre-apt-20261022`, `pre-automove-20261023`). 변경 전 값과 **되돌리는 명령**을 `~/<프로젝트>-qa-state/` 에 남기고, 변경 후 상대 QA 세션에 smoke 를 요청한다.
- **재로그인**(`gnome-session-quit --logout --no-prompt`) 뒤에는 자동 로그인이 적용되지 않아 greeter 에서 멈춘다 → ssh 로 `sudo systemctl restart gdm3`. 그다음 `lock-enabled`·`run.sh` 의 Xwayland 인증 파일·자동 로그인을 확인한다. 자동 로그인은 부팅 직후에만 적용된다.
