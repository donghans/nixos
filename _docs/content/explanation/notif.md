# 알림 센터 (notif) — 알림 기록 조회와 시스템 장애 알림

**상태: 적용 완료 (2026-10-19)**. 구성: `mods/gui/utils/notify-logger.nix`(서비스·런처·타이머), 본체 `mods/_data/notif/`(notif.py, notif_ui.py, 시험), waybar 모듈은 `mods/gui/base/waybar.nix`.

## 쓰는 법
| 하는 일 | 명령 |
|---|---|
| 대화형 화면 열기 | 앱 런처(SUPER+Space)에서 "Notification Center" (또는 `notif ui [all\|apps\|problems\|stats]`) |
| 최근 알림 보기 | `notif list [-n 50] [--app Slack] [--since 3h] [--grep 글자] [--urgent] [--problems]` (1번이 가장 나중에 기록된 것) |
| 같은 앱 알림 묶음 | `notif apps [--since 7d]` |
| 알림 통계 | `notif stats [--since 7d]` — 앱별/시간대별/날짜별 건수, 긴급도 분포 |
| 시스템 문제만 | `notif problems` — 지금 실패한 서비스 + 최근 7일 문제 알림 |
| 복사 | `notif copy N [--body]` (N 은 같은 조건의 `notif list` 번호). 화면에서는 Enter(제목+본문), `c`(본문만) |

화면은 `clipui`/`displayui` 와 같은 외형·조작 규약(검은 배경, 둥근 테두리: 포커스는 하늘색·제목은 테두리 안, 항상 입력 가능한 검색창, ↑↓ 이동, F키, Enter 로 복사하고 종료)을 따르되, 알림 센터답게 **왼쪽 그룹 패널**이 중심이다(처음에는 `clipui` 틀을 그대로 가져와 체크/일괄 복사 같은 클립보드용 기능이 섞였다가, 알림에는 필요 없어서 뺐다).

```
┌ 검색 ─────────────────────────────────────────────┐
┌ 그룹 ──────────┐┌ 알림 · Slack ───────────────────┐
│ 전체       3071 ││ 10-19 15:36 ‼ 서비스 실패: …    │
│ ‼ 시스템 문제 3 ││ 10-19 15:34 긴급 시험 — 본문    │
│ notify-send 1220││ …                               │
│ kitty        724├┌ 미리보기 ────────────────────────┤
│ pasystray    493││ 제목, 본문 전체, 같은 앱 N건 …  │
```
- **그룹**: `전체` · `‼ 시스템 문제`(문제 알림만) · 앱 이름(건수 많은 순, 긴급이 있으면 `‼N`). ↑↓ 로 고르면 **바로 오른쪽 목록이 그 그룹의 알림으로 바뀐다**. 검색어를 넣으면 그룹별 건수도 검색 결과 기준으로 바뀐다.
- 폭이 80 미만이면 그룹 패널이 숨겨지고(F6 으로 보임/숨김), 높이가 16 미만이면 미리보기가 숨겨진다.

| 키 | 동작 |
|---|---|
| 검색창에 입력 | 앱·제목·본문에 **모두 포함**된 글자. 필터: `app:이름`(앱 이름에 포함) `is:problem` `is:urgent` `since:3h`(`m/h/d/w`) |
| ↑ ↓ / PgUp PgDn | 그룹 패널에 포커스가 있으면 그룹, 그 외(검색창 포함)에는 알림 목록 |
| Tab, ← → | 검색창 → 그룹 → 목록 → 미리보기 이동 / 목록에서 ← 는 그룹, 그룹에서 → 는 목록 (목록에서 `g` 도 그룹) |
| Enter | 현재 알림(제목+본문)을 복사하고 종료. 그룹 패널에서는 그 그룹의 목록으로 이동 |
| Esc | 검색어 지우기 → 그룹을 `전체`로 되돌리기 → 종료 |
| 목록에서 c | 본문만 복사(종료하지 않음). 미리보기에서는 c/y 가 선택한 글자(없으면 전체) 복사 |
| F5 / F6 / F7 | 새로고침 / 그룹 패널 보이기·숨기기 / 미리보기 보이기·숨기기 |
| F9 | 통계 대화상자(앱별/시간대별/날짜별/긴급도) — 지금 그룹과 검색 기준 |
| F10 | 서비스 점검(`notif health` 실행: 새 실패 알림 + waybar 갱신, 결과 목록 표시) |

## 구조
- **기록(`notif record`, user 서비스 `custom-notify-logger`)**: `busctl --user --json=short monitor` 로 `org.freedesktop.Notifications.Notify` 호출을 받아 `/var/log/custom-notify-logger/<사용자>.log` 에 한 줄 JSON 으로 남긴다(앱·제목·본문·**긴급도**). 예전의 `dbus-monitor` 출력 글자 파싱은 형식이 바뀌면 깨지고 긴급도를 못 얻어서 바꿨다. 이전 형식(`[시각] [앱] [제목] 본문`)은 그대로 읽는다. 30일 보관(logrotate).
- **문제 알림** = 앱 이름이 `system-health` 이거나 긴급도가 critical(2). 이전 형식 기록에는 긴급도가 없어서 문제로 분류되지 않는다.
- **장애 감시(`notif health`, user 타이머 `notif-health`, 45초 뒤 시작 후 1분마다)**: 시스템과 사용자 systemd 의 실패한 유닛을 확인해 **새로 실패한 것만** 긴급 알림(`system-health`, 최근 로그 6줄 포함)으로 알리고, 상태를 `$XDG_RUNTIME_DIR/notif/health.json` 에 적어 waybar 를 갱신한다(RTMIN+9 신호, 폴링 없음). 복구되면 알림 없이 표시만 사라진다. 로그인 전부터 실패해 있던 유닛은 첫 실행 때 한 번 알린다.
- **waybar**: 실패한 유닛이 있을 때만 빨간 `⚠ N` 이 나타나고(없으면 모듈이 사라짐) 툴팁에 목록, 클릭하면 문제 화면이 열린다. (처음에 쓴 Font Awesome 경고 글리프는 이 폰트에 없어서 `θ` 처럼 보였다 → `⚠`.)

## 알아둘 점
- 기록은 **기록된 순서**를 기준으로 한다(시각으로 정렬하지 않음). 부팅 직후 약 30초는 시스템 시각이 9시간 앞서(`posture.md` 의 "RTC 를 UTC 로 통일" 참고) 그 시각으로 정렬하면 "미래" 알림이 최신으로 올라왔다. 표시되는 시각 자체는 그 구간에서는 틀린 값이다(윈도우를 새로 설치할 때 RTC 를 UTC 로 통일하면 사라진다).
- 알림 데몬은 mako 이고 `notif` 는 mako 의 기록(`makoctl history`)이 아니라 위의 자체 기록을 쓴다 — mako 의 기록은 재시작하면 사라지고 건수 제한이 있다.
- 시스템 유닛의 실패 원인 로그는 사용자 권한으로 못 읽을 수 있다(그러면 알림 본문이 "(로그를 읽지 못했습니다)").
- 시험: `mods/_data/run-tests.sh` (notif 35개 + 화면 23개; 화면은 textual 이 있는 python 필요). 실제 확인: 실패하는 임시 유닛(`systemd-run --user --unit=x false`)을 만들어 알림·waybar 표시·해소를 확인했다 — 확인 후 `systemctl --user reset-failed x`.
- **복사하고 종료했는데 창이 빈 화면으로 남던 문제 (2026-10-19, notif 와 clipui 둘 다)**: Enter 로 복사하면 `wl-copy` 가 클립보드 내용을 계속 제공하려고 백그라운드로 남는데, 그 프로세스의 stderr 가 kitty 의 터미널(pty)에 물려 있어서 kitty 창이 닫히지 않았다(`wl-copy` 의 fd 2 가 `/dev/pts/0`). 프로세스(`notif ui`)는 정상 종료(status 0)하고 있었다. 복사할 때 stdout/stderr 를 `/dev/null` 로 돌리자 창이 닫혔다. `hyprctl dispatch 'hl.dsp.send_shortcut({ mods = "", key = "Return", window = "class:^notif$" })'` 로 대상 창에만 Enter 를 보내 실제 창에서 고침 전/후를 확인했다(시험은 `copy_text` 가 출력을 분리하는지를 검사).
- **pasystray 의 "New sink" 알림 반복**: 모니터 연결과 무관하게 이 노트북 오디오 칩(sof-hda-dsp)에는 HDMI/DP 출력 3개가 항상 있고, pasystray 가 (다시 시작될 때마다) 이 출력들과 마이크·스피커·헤드폰을 "새 장치"로 한꺼번에 알렸다. 터진 시각이 `nixup home` 을 돌린 시각과 겹쳤다(오늘 14:08~16:10). 모니터 오디오를 쓰지 않으므로 `hosts/msi-summit-me.nix` 에서 WirePlumber 규칙(`~/.config/wireplumber/wireplumber.conf.d/51-no-hdmi-audio.conf`, `node.disabled = true`)으로 HDMI 출력 노드를 숨겼다 — `wpctl status` 의 HDMI 출력 3개가 0개로 줄고 스피커/독 오디오는 그대로. 스피커·헤드폰·마이크 알림은 pasystray 재시작 때 여전히 나올 수 있다(끄려면 `pasystray --notify=none`).

