# qa-desktop — 화면 확인용 QA 데스크톱 (incus VM)

사용자가 화면을 함께 보면서 AI(Claude Code)가 브라우저를 조작해 작업물을 확인하는 **공용 QA 환경**. incus VM `qa-desktop`(Ubuntu Desktop 26.04, GNOME 50 Wayland, 4CPU/8GiB) 하나를 여러 프로젝트의 QA 세션이 나눠 쓴다.
이 시스템은 donghans 워크스테이션 전용이라 프로젝트 저장소에 추적하지 않고 여기에 둔다. 운영 절차는 스킬 `donghans-qa-desktop`(`mods/_data/claude-skills/donghans-qa-desktop/`), 전역 지침에는 호출 조건과 안전 규칙만 들어간다(`mods/devel/apps/llm-cli.nix`).

## 구성
| 부분 | 위치 | 역할 |
|---|---|---|
| 스위치 | `mods/sys/services/qa-desktop.nix` (호스트 toml `qa-desktop = true`, 프리셋 기본 꺼짐) | 켠 호스트의 `~/.claude/CLAUDE.md` 에 지침을 넣고 스킬을 등록. 설치·설정은 하지 않는다 |
| 지침 | `mods/devel/apps/llm-cli.nix` 의 `qaDesktopInstructions` | 호출 조건 + 승인 필요 작업 + 데스크톱 번호 묻지 않기 |
| 스킬 | `mods/_data/claude-skills/donghans-qa-desktop/` | 접속·실행·창 배치·공유 규칙·복구 본문 + `scripts/ws.py`·`snap.py` |
| VM 선언·생성 | `mods/sys/services/qa-desktop.nix` 의 `decl`(크기·이미지·프로젝트 규칙) + `qa-desktop-ctl`(`mods/_data/qa-desktop/qa_desktop_ctl.py`) + `provision.sh` | 사용자 서비스 `qa-desktop-ensure` 가 로그인 때 `ensure`: **없으면 만들고, 있으면 건드리지 않는다**(2026-10-23) |
| 프로젝트 쪽 | VM 안 `~/qa-playwright/`(ToT 소유, 공유 Playwright 1.63·node 22), `flow_<프로젝트>/` | 스크립트는 프로젝트별 디렉터리 |

## 왜 이렇게 만들었나
- **Docker headless 와 역할이 다르다.** 전역 지침의 「브라우저 자동화는 Docker 에서만」은 호스트 오염 방지가 목적이다. 이 VM 은 호스트에 브라우저를 두지 않으면서, 사용자가 **실시간으로 화면을 보며** 하는 확인과 Flutter 웹(CanvasKit)처럼 접근성 트리가 필요한 확인을 맡는다.
- **VM 은 하나, QA 세션은 프로젝트별.** VM 을 프로젝트마다 복제하면 호스트 메모리(8GiB/대)가 부족하다(호스트 여유 약 8GB, win11 VM 도 상시 실행). 대신 화면은 **가상 데스크톱**으로, 파일은 **디렉터리 규칙**으로, 시간은 **시작 알림**으로 나눈다.
- 요청이 잦아 충돌이 반복되면 단일 QA 세션 + 요청 큐로 바꾸는 안이 있다(미결정, 지금은 불필요로 판단).

## 화면 분리 — 확인된 동작 (2026-10-23)
| 확인 | 결과 | 방법 |
|---|---|---|
| 안 보이는 데스크톱의 창이 멈추나 | **안 멈춘다**(DOM) — `visibilityState` 계속 visible, 약 58fps(보일 때 60), 스크린샷 19~66ms 12/12, 클릭 정상 | Playwright headed Chromium(Wayland, 완화 플래그 없음) + `ws.py` 로 데스크톱 전환 |
| 스크린샷이 낡은 프레임이 아닌가 | **최신**(lag 1프레임) 17/17 | 프레임 번호를 DOM 블록 16개의 비트 패턴으로 그려 스크린샷 픽셀을 디코딩해 비교 |
| `--class=genple-qa` 창이 데스크톱 2 로 가나 | **간다**(데스크톱 1 에는 안 뜸) | Auto Move Windows 규칙 `genple-qa.desktop:2`, 사용자 눈으로 확인 |
| `--class` 없는 창(ToT 방식)이 영향받나 | **안 받는다**(현재 데스크톱에 뜸) | `ws.py home` 으로 데스크톱 1 강제 후 창이 보이는지 확인 |
- **미검증**: WebGL·CanvasKit 의 비가시 렌더링(Flutter 웹). 로그인(ToT 콘솔) smoke.
- **이상 현상(원인 미확인)**: WebGL 캔버스를 `locator.screenshot()` 으로 찍으면 이후 캔버스가 비고 깨진 이미지 아이콘이 찍힌다. 렌더러는 SwiftShader(소프트웨어 GL). 페이지 단위 `page.screenshot` 은 첫 장에서 정상이었다. ToT 스크립트는 페이지 단위만 쓴다(저장소 확인 범위).

## 사람 없이 화면 확인하기
- `snap.py <png>`: 화면 캡처. GNOME 의 `org.gnome.Shell.Screenshot` 은 AccessDenied 라 **Mutter ScreenCast + PipeWire + GStreamer** 로 찍는다. 호스트의 QEMU 모니터 소켓(`/run/incus/qa-desktop/`)은 권한이 막혀 있어 쓰지 않는다.
- `ws.py right|left|home|escape`: 데스크톱 전환(`home` 은 ← 를 8번, `escape` 는 GNOME 개요 닫기). `org.gnome.Shell` 의 Eval·GetWindows 가 막혀 있어 Mutter RemoteDesktop 가상 키 입력(Ctrl+Alt+→/←, Esc; Super 키는 개요를 열어 쓰지 않는다)으로 한다. 창이 어느 데스크톱에 있는지 직접 조회할 수 없으므로 「데스크톱 1 로 강제 → 창이 보이는가」「snap.py 로 확인」으로 판정한다.
- 둘 다 VM 안에서 실행하며 VM 에 설치할 것이 없다(python3 gi, gst-launch-1.0, pipewire 가 기본 설치돼 있음).

## 시험에서 발견·수정한 것 (2026-10-23)
- **`ws.py home`(Super+Home) 뒤 캡처가 GNOME 개요(Activities) 화면인 적이 있다.** genple QA 세션이 시험 중 지적했고 직접 재현도 1회 했지만, ToT QA 시험(캡처 원본 재확인)과 이어서 한 3회 재현(다른 데스크톱에서 home / 이미 1번에서 home / escape 후 home)에서는 모두 정상 바탕화면이었다 — **조건이 확정되지 않은 간헐 현상**이다. 추정 원인은 Super 키를 떼는 동작이 GNOME 의 「개요 열기」와 겹치는 것. Super 를 쓰지 않으면 가능성이 없으므로 `home` 을 Ctrl+Alt+← 8번으로 바꾸고, 이미 열린 개요를 닫는 `escape` 를 추가했다. 판정(창이 어느 데스크톱인지) 결론은 두 방식 모두 같았다. 검증: escape → right → home → left 를 캡처해 작업 공간 표시 위치로 판정(맨 끝에서 순환 없음), home 캡처는 개요가 아닌 실제 바탕화면.
- **가상 데스크톱은 동적이다.** `gsettings` 는 `dynamic-workspaces=false`, `num-workspaces=4` 인데 실제로는 창이 있는 데스크톱 + 끝의 빈 하나만 존재한다(창 없을 때 2개). 규칙 `genple-qa.desktop:2` 가 동작하는 이유(2번은 항상 있다)이기도 하다. 사용자가 처음 본 「3개」는 genple-qa 창이 2번에 있을 때의 모습.
- 실사용 시험 결과: ToT QA 세션(file:// 페이지, `--class` 없음) — 창이 데스크톱 1 에 보이고 2 에 없음. genple QA 세션(`--class=genple-qa`, genple 첫 화면 `http://10.100.0.1/` → 302 → `/welcome`) — 데스크톱 1 에 없고 2 에 보임. 알림 규칙(시작·완료)이 두 세션 사이에 실제로 오갔다. 새로 띄운 genple 세션은 반영 전에 시작해 전역 CLAUDE.md 절은 없었지만 스킬은 자동으로 목록에 보였다.
- 로그인 smoke 는 어느 쪽도 하지 않았다(미검증).

## VM 선언·자동 생성 (2026-10-23)
**전에는** VM 이 incus 에 직접 만든 것(Ubuntu 설치 ISO + 자동설치 시드 볼륨)이라 새 호스트에서는 재현할 수 없었다. **지금은** 호스트 스위치 `qa-desktop = true` 만 켜면 `qa-desktop-ctl` 이 설치되고 로그인 때 서비스가 VM 을 보장한다(`nixup home` 만으로 배포 — OS 재빌드·sudo 불필요).
- **`ensure`**: VM 이 없으면 `images:ubuntu/26.04/desktop`(GNOME 50 Wayland, 1.4GB)으로 만들고 프로비저닝한다. **이미 있는 VM 은 건드리지 않는다** — 이 도구가 만든 표식(`user.qa-desktop.*`)이 없는 VM 은 「채택」만 한다(운영 VM 이 그렇다; `provision` 도 `--yes` 없이는 거부). 생성 도중 멈춘 VM(`state=creating`)은 이어서 프로비저닝한다.
- **프로비저닝(`provision.sh`, 멱등)**: 이미지의 `ubuntu`(uid 1000)를 `qa` 로 이름 변경 · 호스트 키만 받는 ssh · GDM 자동 로그인 · 화면 잠금·절전 끔(시스템 dconf) · Auto Move Windows 켬 + 프로젝트별 규칙 · Playwright(`~1.63.0`)+Chromium · `run.sh`·`~/qa-tools/{ws,snap}.py` · 프로젝트별 `.desktop`·디렉터리.
- **선언 변경 감지**: 선언(스크립트·도구·규칙·버전)의 지문을 VM 에 기록해 두고, 바뀌면 `ensure` 가 알린다(자동 재실행은 안 함 → `qa-desktop-ctl provision`). 새 프로젝트의 창 배치 규칙은 `decl.projects` 에 「이름 = 데스크톱 번호」 추가 → `nixup home` → `provision`.
- **`incus-win11` 과의 차이**: win11 은 프로필·설치 ISO(autounattend 포함)만 선언하고 **인스턴스는 사람이 만든다**(Windows ISO·라이선스를 선언할 수 없어 자동 생성 불가). qa-desktop 은 서버의 `incus-*-lxc.nix` 관례(「없으면 만든다」)를 따른다.
- **측정(이 호스트, 이미지 캐시됨)**: 없는 상태에서 `ensure` 235초(생성 12초 + 프로비저닝 약 4분) · 재프로비저닝 11~120초(Playwright 재설치 여부에 따라) · 멈춘 VM 복구 · 선언 변경 감지 · `status`. 검증은 임시 VM(`qa-desktop-test`, 3GiB)로 했고 운영 VM 은 변하지 않음(설정 해시 동일).
- **시험이 잡아낸 것**: ① 완료 파일(`gnome-initial-setup-done`)이 오히려 **업그레이드 마법사**를 켠다(조건: done 이 있고 `upgrade-<버전>-done` 이 없을 때) → 사용자 유닛을 마스크 ② 세션을 강제 종료하며 생긴 gnome-shell 크래시 보고가 새 세션에 apport 대화상자로 뜸 → 보고 삭제 + apport 끔 ③ `incus list <이름>` 은 접두 일치라 `qa-desktop-test` 가 `qa-desktop` 을 오염 → `^이름$` 정확 일치 ④ **실행 중인 VM 의 스냅샷이 프로비저닝 직후 수 분 막힘**(수동 재시도는 0.2초; 원인 미확정) → 최초 생성 때만 껐다(1초)·오프라인 스냅샷(0초)·켜기(10초) ⑤ Playwright `^1.63.0` 이 1.64 로 올라감 → `~1.63.0`.
- **한계**: 새 VM 은 기존 운영 VM 과 **완전히 같지는 않다**(기존은 설치 ISO 로 설치, 새것은 이미지 기반; 한 세대 차이 — Playwright Chromium 리비전·패키지 버전). 운영 VM 에는 `incus-agent` 가 없어 `incus exec` 프로비저닝이 불가해서 **채택만** 하고, 갈아타려면 새 VM 을 만들어 옮긴다(사용자 결정). 다른 호스트(노트북)에서의 서비스 동작은 이 호스트의 임시 VM 으로만 검증했다(같은 프리셋).

## 처음 보는 세션·프로젝트가 막히지 않게 (2026-10-23 감사)
- 스킬 `donghans-qa-desktop` 에 **사전 점검**(VM·키·접속·프로젝트 규칙·점유 확인)을 넣었다. 어긋나면 임의로 만들거나 고치지 않고 사용자에게 알린다(VM 생성·설정은 승인 필요 작업).
- **점유 알림은 `scripts/occupy.py`(VM 안의 `/tmp/qa-desktop-occupancy/`)가 기본 수단**이다: 세션 간 메시지 도구가 없는 에이전트도 같은 정보를 읽고 쓴다. 락이 아니라 알림이고, 다른 프로젝트 점유·chrome 이 떠 있으면 경고(종료 코드 1). 메시지 도구는 가속 수단.
- 프로젝트 지침 파일 규약·`context.py --init`·worktree 처리는 스킬 `donghans-qa` §0-A, 에이전트 결합 분석은 `llm-tooling-portability.md`.

## 운영 사실 (VM)
- 접속은 SSH 키만(`~/.ssh/qa_desktop_ed25519`, 계정 `qa`, 비밀번호 없음). `incus exec` 는 VM 에이전트가 없어 안 된다.
- 화면 잠금 해제·절전 끔(`lock-enabled false`, `idle-delay 0`)이 전제다. 계정에 비밀번호가 없어 잠기면 GUI 로 못 푼다.
- **재로그인 주의**: `gnome-session-quit` 으로 로그아웃하면 GDM 자동 로그인이 적용되지 않고 greeter 에서 멈춘다(자동 로그인은 부팅 직후에만). `sudo systemctl restart gdm3` 으로 복구(2026-10-23 실제로 이렇게 복구, VM 재시작·스냅샷 복원 불필요). 복구 후 자동 로그인·`lock-enabled`·`run.sh` 의 Xwayland 인증 파일명(재로그인마다 바뀜)을 확인한다.
- 크래시: incus 상태 RUNNING 인데 ssh 가 `No route to host`. 원인 미확정(2026-09-08 이후 `raw.qemu=-cpu host` 와 메모리 16→8GiB 로 재현 안 됨). 복구는 `journalctl -b -1` → `incus restart qa-desktop --force`.
- 스냅샷: `genie-test-base`(10-02), `pre-2604`(10-16), `pre-apt-20261022`, `pre-automove-20261023`. 새 스냅샷은 위험한 변경 직전에 만든다.

## 2026-10-23 변경 기록 (genple 세션, 사용자 승인)
VM 에서 한 일: apt 로 `gnome-shell-extension-auto-move-windows`(50.0-1) + `gnome-shell-extensions-common` 설치(업그레이드·삭제 없음), 확장 활성, `application-list=['genple-qa.desktop:2']`, `~/.local/share/applications/genple-qa.desktop`(`StartupWMClass=genple-qa`), GNOME 재로그인 1회. `focus-new-windows` 는 `smart` 그대로(바꾸지 않음 — 창이 지정 데스크톱에 뜨면 포커스를 가져가도 보는 화면의 입력을 가로채지 않고, ToT 영향이 미확인).
변경 전 값·되돌리는 명령은 VM 의 `~/genple-qa-state/before.txt`·`changes.txt`:
```bash
gnome-extensions disable auto-move-windows@gnome-shell-extensions.gcampax.github.com
gsettings reset org.gnome.shell.extensions.auto-move-windows application-list
rm ~/.local/share/applications/genple-qa.desktop
sudo apt-get remove -y gnome-shell-extension-auto-move-windows gnome-shell-extensions-common
```
스냅샷으로 되돌리면(`pre-automove-20261023`) 그 사이 ToT 쪽 변경도 함께 사라진다 — 마지막 수단.

## 새 프로젝트를 붙이려면
1. VM 에 `~/.local/share/applications/<프로젝트>-qa.desktop`(`Exec=chromium %U`, `StartupWMClass=<프로젝트>-qa`, `NoDisplay=true`) 생성.
2. `gsettings get org.gnome.shell.extensions.auto-move-windows application-list` 로 현재 목록을 읽고 **기존 항목을 유지한 채** `<프로젝트>-qa.desktop:<번호>` 추가.
3. 스크립트는 `~/qa-playwright/flow_<프로젝트>/`, 창은 `--class=<프로젝트>-qa`. 변경 전 값은 `~/<프로젝트>-qa-state/` 에 남긴다. 확장은 이미 켜져 있어 재로그인은 필요 없다(새 `.desktop` 은 즉시 인식되는지 확인).
4. 이 문서의 「화면 분리」 표와 스킬의 「현재 규칙」을 갱신한다.
