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

화면 단축키: `a` 전체 / `g` 앱별 / `p` 문제 / `s` 통계 / `r` 새로고침 / 검색창에 입력하면 앱·제목·본문 필터 / 앱별 화면에서 Enter 하면 그 앱만.

## 구조
- **기록(`notif record`, user 서비스 `custom-notify-logger`)**: `busctl --user --json=short monitor` 로 `org.freedesktop.Notifications.Notify` 호출을 받아 `/var/log/custom-notify-logger/<사용자>.log` 에 한 줄 JSON 으로 남긴다(앱·제목·본문·**긴급도**). 예전의 `dbus-monitor` 출력 글자 파싱은 형식이 바뀌면 깨지고 긴급도를 못 얻어서 바꿨다. 이전 형식(`[시각] [앱] [제목] 본문`)은 그대로 읽는다. 30일 보관(logrotate).
- **문제 알림** = 앱 이름이 `system-health` 이거나 긴급도가 critical(2). 이전 형식 기록에는 긴급도가 없어서 문제로 분류되지 않는다.
- **장애 감시(`notif health`, user 타이머 `notif-health`, 45초 뒤 시작 후 1분마다)**: 시스템과 사용자 systemd 의 실패한 유닛을 확인해 **새로 실패한 것만** 긴급 알림(`system-health`, 최근 로그 6줄 포함)으로 알리고, 상태를 `$XDG_RUNTIME_DIR/notif/health.json` 에 적어 waybar 를 갱신한다(RTMIN+9 신호, 폴링 없음). 복구되면 알림 없이 표시만 사라진다. 로그인 전부터 실패해 있던 유닛은 첫 실행 때 한 번 알린다.
- **waybar**: 실패한 유닛이 있을 때만 빨간 `⚠ N` 이 나타나고(없으면 모듈이 사라짐) 툴팁에 목록, 클릭하면 문제 화면이 열린다. (처음에 쓴 Font Awesome 경고 글리프는 이 폰트에 없어서 `θ` 처럼 보였다 → `⚠`.)

## 알아둘 점
- 기록은 **기록된 순서**를 기준으로 한다(시각으로 정렬하지 않음). 부팅 직후 약 30초는 시스템 시각이 9시간 앞서(`posture.md` 의 "RTC 를 UTC 로 통일" 참고) 그 시각으로 정렬하면 "미래" 알림이 최신으로 올라왔다. 표시되는 시각 자체는 그 구간에서는 틀린 값이다(윈도우를 새로 설치할 때 RTC 를 UTC 로 통일하면 사라진다).
- 알림 데몬은 mako 이고 `notif` 는 mako 의 기록(`makoctl history`)이 아니라 위의 자체 기록을 쓴다 — mako 의 기록은 재시작하면 사라지고 건수 제한이 있다.
- 시스템 유닛의 실패 원인 로그는 사용자 권한으로 못 읽을 수 있다(그러면 알림 본문이 "(로그를 읽지 못했습니다)").
- 시험: `mods/_data/run-tests.sh` (notif 32개 + 화면 7개; 화면은 textual 이 있는 python 필요). 실제 확인: 실패하는 임시 유닛(`systemd-run --user --unit=x false`)을 만들어 알림·waybar 표시·해소를 확인했다 — 확인 후 `systemctl --user reset-failed x`.
