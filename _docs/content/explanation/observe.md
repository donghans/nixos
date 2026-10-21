# observectl / observe — 관측 시스템 (전력·프로세스 프로파일, 유틸리티 이벤트 로그)

전력 측정과 우리가 만든 유틸리티(displayui, dispctl, posture 등)를 **추정이 아니라 기록으로** 확인하기 위한 도구 묶음. 본체는 `mods/_data/observe/`, NixOS 모듈은 `mods/sys/services/observectl.nix`(호스트 toml 의 `[mods.sys.services] observectl = true`).
Netdata(1초/10초 시스템 지표, 7일)는 그대로 쓰고, observectl 는 Netdata 가 못 보는 것을 맡는다: 스레드 단위 자발적 문맥 전환, **누가 CPU 를 깨우는지(ftrace·eBPF)**, 패키지 C-state(MSR), 유틸리티 이벤트, 실험 표지와 통계 판정.

## 켜고 끄기 (오버헤드 0 설계)
- `observectl on [L0|L1]` / `observectl off` — 제어 파일(`/var/lib/observe/control.json`, 그룹 users 쓰기 가능)만 바꾼다. sudo 불필요.
- 수집기(root)는 systemd **path 유닛**이 제어 파일 변경이나 `requests/` 에 파일이 생길 때만 띄우고, 꺼져 있고 할 일이 없으면 15초 뒤 스스로 종료한다. 꺼져 있는 동안은 **프로세스 자체가 없다**.
- 수준: **L0** 30초 간격(전력, 패키지 C-state, IRQ/GPE, 프로세스별 CPU(코어 1개=100%)·자발적 문맥 전환/s·RSS, 장치 상태) / **L1** 5초 간격 + 스레드별 상위, 프로세스별 IO. 표본은 `/var/lib/observe/data/samples-YYYYMMDD.jsonl`(보존 14일·1GiB, 재부팅해도 남음).
- 개인정보: 프로세스는 comm 과 exe 이름만 기록. 명령 인자·URL·입력한 글자는 기록하지 않는다.

## 자주 쓰는 명령
| 하고 싶은 것 | 명령 |
|---|---|
| 지금 상태 | `observectl status` |
| 구간 요약(상태/VT/SSID/덮개/AC/표지/실제 Wi-Fi 절전별 `--by wifips`) | `observectl window --since 11:00 --until 11:30 --by state` |
| 낮은 전력 상태(low) 전환 시각 | `observectl states --since 3h` |
| 상위 프로세스·스레드 | `observectl top --by ctxsw`(자발적 문맥 전환/s) / `--by cpu`(코어 1개 기준 %) / `--by thr`(L1) / `--by io`(L1) — `wake` 는 `ctxsw` 의 옛 이름 |
| **누가 CPU 를 깨우나**(타이머/하이타이머 함수, IRQ, workqueue) | `observectl wakers 10` (`--waking` 이면 깨우는 쪽 프로세스도) |
| 그 순간 무슨 일이 있었나 | `observectl timeline --at 12:09:37 --span 60` (표본 + 유틸리티 이벤트 + journal + 커널 로그를 시간순으로 합침) |
| 유틸리티 이벤트 | `observectl events --comp displayui --level debug --grep key` |
| 이벤트 로그 수준 변경(재시작 없이) | `observectl level displayui trace` |
| drm.debug 잠깐 켜기 | `observectl drmdebug 15` → `observectl timeline --at <중간시각> --journal all` |
| Hyprland TRACE 로그(다음 로그인부터) | `observectl hyprtrace on` (로그량이 많아 전력 측정과 동시에 쓰지 말 것) |
| 디스플레이 debugfs 스냅샷 | `observectl display` — **읽는 것이 디스플레이를 깨워 낮은 상태를 깨뜨릴 수 있음** |

## 전력 A/B 측정 절차 (이 절차로 잰 것만 "측정"으로 표기)
**틀을 쓴다**: `examples/abab_lib.sh` 를 불러와 `abab_set_a/b`·`abab_verify_a/b`·`abab_restore` 만 정의하고 `abab_run` 을 부른다(예: `examples/netdata_abab.sh`). 틀이 아래를 대신 지켜 준다 — Ctrl-C/TERM 때 복구하고 **끝낸다**, 시작 때의 덮개·AC 가 구간 사이에 바뀌면 즉시 중단(예: 중간에 덮개를 엶), 조건을 바꾼 직후 실제 값을 읽어 확인, 복구는 정확히 한 번, 마지막 `ab` 에 `--require dev.lid=… --require pw.ac=…` 자동 부착.
1. `observectl on L0`(또는 L1)을 켜고 안정화(≥ 2분). 어댑터/덮개/VT/Wi-Fi 상태를 `observectl status` 로 확인. **어댑터는 뽑고**, 시험 종류에 맞게 덮개를 닫거나(대리 조건) 열어 두고(실제 사용) 손대지 않는다.
2. **A 와 B 를 번갈아 3쌍 이상(ABABAB)**, **구간은 5분 이상**: 순간 V×I 는 30초 표본이라 구간이 짧으면 표본이 4~5개뿐이고, 누적 계량(1 mAh ≈ 15 mWh 단위)은 구간이 짧을수록 오차가 크다(오차 ≈ 15 mWh ÷ 구간 시간: 5분이면 ±0.18 W, 90초면 ±0.6 W). **스크립트에서 root 명령은 `/run/wrappers/bin/sudo` 를 써야 한다**(틀이 PATH 를 맞춘다).
3. `observectl ab --since <T0>` — 기본은 **psys · 패키지 · 순간 V×I · 누적 계량을 한꺼번에** 보여 주고, 신뢰가 낮은 지표(구간당 표본 8개 미만의 V×I, 오차가 임계의 절반을 넘는 계량)는 표시하고 종합에서 뺀다. 신뢰 가능한 지표끼리 부호가 다르면 "불확실". 자동 검증: 덮개·AC 가 구간마다 다르면 **무효**(`--allow-mixed` 로 허용), SSID 가 다르면 경고, 짧아서 버려진 구간에서 조건이 달랐으면 경고. 추가 검증은 `--expect-a/-b 경로=값`(예: `dev.wifi.ps=off`), `--require 경로=값`. Netdata 가 켜져 있으면 **Netdata 1초 평균(psys·패키지·V×I)** 도 같은 표에 넣는다(`--no-netdata` 로 뺌). 구간 일부라도 Netdata 가 꺼져 있었으면(커버리지 90% 미만) 그 지표는 "관측 공백"으로 판정하지 않는다 — 쌍이 어긋나기 때문이며, 나머지 지표 판정에는 영향이 없다.
4. 판정 문구: **3쌍 이상**이고 모든 쌍이 같은 부호이며 임계(0.3 W) 이상이면 "확인(측정)", 2쌍이면 **"일치(약함)"**, 그 외 "불확실". (2쌍은 부호검정 p 가 0.5 라 우연과 구분되지 않는다 — 2026-10-21 #58 에서 순간 V×I 가 다른 지표와 반대였는데도 옛 도구가 "확인"이라 한 일이 계기.)
5. 같은 구간에 low/high 상태가 섞였다는 경고가 나오면 `observectl window --by state` 로 확인 — 낮은 상태 전환이 효과를 가렸을 수 있다.
6. 결과는 `power-evidence.md` 의 장부에 근거 수준(측정 / 측정(약) / 유보 / 추정)과 함께 기록.

## 낮은/높은 상태 분류(휴리스틱)
`state = low` ⇔ 패키지 pc10 잔여율 ≥ 5%. 근거: powertop 측정에서 낮은 상태 pc10 17~24%, 높은 상태 0%. 낮은 상태의 하드웨어 정체는 "eDP 파이프 꺼짐"(display_snap 비교)이지만 pc10 은 그 결과 지표다. 이 분류가 틀리는 경우가 보이면 기준을 조정한다.

## 우리 유틸리티에 이벤트 로그 붙이기
- Python: `from observe_events import Events; ev = Events("컴포넌트"); ev.debug("key", key="enter")`, `with ev.span("apply"): …`. 수준은 제어 파일에서 읽어 1초 캐시 → `observectl level` 로 즉시 변경. 기록 실패는 호출자를 죽이지 않는다.
- 셸: `observe-emit lid-policy info lid lid=closed`.
- 위치: `~/.local/state/observe/events-YYYYMMDD.jsonl`(재부팅해도 남음, 줄마다 즉시 기록되어 크래시 직전까지 남음).
- **붙어 있는 곳**: `displayui`(키 이름과 포커스 위젯, 포커스 이동, 모드 선택, 확인 창 결과), `dispctl`(모든 hyprctl 호출, 적용 계획·규칙, 창 이동, 트랜잭션). 다른 유틸리티(posture-daemon, hypr-input-policy, lid-policy, notif)는 같은 방식으로 붙이면 된다(아직 안 붙음).
- 시험은 `OBSERVE_STATE_DIR`/`OBSERVE_DATA_DIR` 로 경로를 격리한다(tests/run.sh 가 설정).

## 한계
- 수집기 자체의 **CPU 비용(측정)**: L0(30초) 코어 1개의 약 0.35%, L1(5초+스레드 스캔) 약 1.9%. `observectl off` 뒤 15초 안에 프로세스가 사라진다. **전력(W)으로의 비용은 아직 측정하지 않았다** — 독립 계량(Netdata 의 RAPL/배터리 차트)으로 켬/끔을 번갈아 재야 한다. 그때까지 **전력 A/B 에는 L0 만 쓰고**(L1 은 프로파일링 전용), 표본에 수집기가 켜져 있었다는 사실이 남으므로(`observectl status`) 결과 해석에 반영한다.
- **측정 환경 자체의 부하(교란 요인)**: 목적은 Wayland 세션 사용 시 배터리 최적화이고, 내 Claude 세션은 Wayland 위에서 돌리지 않으려고 VT2(kmscon)에 둔다. 그런데 VT2 가 활성일 때 내가 화면을 갱신(스피너 등)하면 약 +1.3 W 가 섞인다(kmscon·Claude CPU 각 약 18%, power-evidence.md #34). **측정 중에는 내 세션을 한가하게 두고**(턴을 끝내고 백그라운드로 기다림), 같은 구간의 `observectl top --by cpu` 로 교란이 없었는지 확인한다.
- MSR PC-state 는 `msr` 모듈이 필요(`boot.kernelModules`), 패키지 값만 본다(코어별 C-state 는 cpuidle 의 평균).
- `observectl wakers` 는 ftrace 이벤트 4종(timer, hrtimer, irq, workqueue; `--waking` 시 sched_waking)을 N초 켠다 — 이벤트 수가 많은 시스템에서는 8MiB/CPU 버퍼가 넘칠 수 있다(결과의 총 건수가 매우 크면 `sec` 를 줄일 것).

## 알려진 문제와 고친 것
- **표지(mark)가 한 표본 늦게 반영되던 버그**(2026-10-20): 수집기가 제어 파일을 루프 시작에서만 읽어서, `observectl mark` 변경이 다음 표본에야 반영됐다. 실험 사이의 `mark --clear` 뒤 잔여 표본이 이전 조건으로 남아 `ab` 의 구간이 5개(BABAB)로 갈리고 "무효" 판정이 났다. 수정: 표본 직전에 제어 파일을 다시 읽고, `ab` 는 표본 5개 미만 구간을 제외(`--min-samples`).
- **스크립트의 sudo 경로**: PATH 앞에 `/run/current-system/sw/bin` 을 두면 setuid 가 아닌 `sudo` 가 잡혀 조건이 안 바뀐다 → `/run/wrappers/bin` 을 앞에 둘 것. 그래서 `ab --expect-a/--expect-b` 로 실제 조건을 검증한다.

## 예제 스크립트 (`mods/_data/observe/examples/`)
- `abab_lib.sh` — **번갈아(ABAB) 측정 틀**(신호 처리·덮개/AC 변화 자동 중단·적용 확인·복구 한 번·`ab` 자동 검증). 새 시험은 이 틀에 조건 적용 함수만 채워서 만든다. `netdata_abab.sh` 가 사용 예.
- `wifi_abab.sh` — 검증형 Wi-Fi 절전 A/B(바꾼 직후 실제 값 확인, `--expect-*` 로 판정 검증). 틀 도입 이전 스크립트.
- `wifi_switch.sh` — Wi-Fi 프로필 전환 + 게이트웨이 핑 실패 시 자동 복귀(원격 세션 보호).

## 어느 지표를 믿을까 (2026-10-20 검증)
- **배터리 V×I**(`batt_w`)는 누적 계량기와 2~4% 안에서 맞는다 → 실제 방전 전력의 기준으로 쓴다. 다만 순간값이라 표본 하나의 변동이 크므로(sd 0.4~0.5 W) **구간 평균**으로만 쓴다.
- **누적 계량**(`pw.q_uah`, `observectl energy`)은 1 mAh(≈15 mWh) 단위의 누적 전하라 **10분 이상 평균**에 가장 정확하다(짧은 구간은 양자화가 큼).
- **psys 는 총 소비의 약 1 W 를 못 본다**(패널·SSD·EC·전압 변환 손실 등). 같은 부팅·같은 상태 안에서 *상대 변화*를 볼 때만 쓰고, **부팅 간 절대 비교나 "전체 이득" 주장에는 쓰지 않는다.**
- 패키지 W 와 C-state 잔여율(pc8/pc10)은 "SoC 안에서 무슨 일이 일어났는가"를 보는 보조 지표다.
- `ltr_probe.py`(root) — 90초 동안 Wi-Fi 모듈(CNV)의 LTR 과 패키지 C-state 를 같이 잰다(패키지가 왜 깊게 못 자는지).
- `input_rate.py`(root) — 30초 동안 입력 장치별 이벤트 개수만 센다(내용은 기록 안 함).
- `socks5_udp_test.py` — SOCKS5 서버가 UDP 를 중계하는지 직접 시험한다.

## 자동 포착: `pc3-stuck`
수집기는 **높은 상태이고 패키지가 PC3 에 20회(10분) 연속 막혀 있으면**(pc3 ≥ 30%, pc6+pc8+pc10 < 1%) 그 표본에 `flag = "pc3-stuck"` 를 달고, **절전 설정 스냅샷**(`power_knobs`)을 `/var/lib/observe/data/knobs-<epoch>.json` 에 한 번(시간당 최대 1회) 저장한다. 읽기 전용이라 측정에 영향이 없다.
다음에 이 상태가 생기면: `observectl window --by flag`, 저장된 스냅샷을 기준 스냅샷과 `power_knobs.py diff` 로 비교한다(기준은 정상 상태에서 `power_knobs.py save` 로 만들어 둔다). 2026-10-20 오후에 2시간 41분 지속된 상태의 원인은 이 도구가 없어서 못 잡았다(#48~#51).


## `powerui` — 전력 현황 TUI (2026-10-21)

`powerui` (앱 런처에서는 "Power Monitor") 는 수집기가 남긴 표본을 그래프와 표로 보여주는 Textual 앱이다. 본체는 `mods/_data/observe/powerui.py`(화면) · `powerview.py`(rich 조각) · `powerdata.py`(증분 읽기·집계·추정) · `powergraph.py`(점자 그래프 계산).

**그래프·표 하나마다 박스 하나**(btop 처럼 제목이 달린 테두리, 아래 테두리에 지금/평균/최소/최대).

| 탭 | 박스 |
|---|---|
| 1 지금 | 현황(전원·잔량 Wh·psys/배터리/패키지 W·low/high·**PSR 모드/싱크**·밝기·덮개·Wi-Fi 절전·**남은 시간 추정**) / 최근 30분 psys / 최근 30분 배터리 |
| 2 시계열 | 배터리 소비 / psys / 패키지 / 배터리 잔량 / 상태·PSR·전원 띠. 구간 `r`: 1시간·6시간·오늘·3일 |
| 3 비교 | 그룹별 평균 표(`g`: 상태·PSR 켬끔·AC·덮개·VT·부팅, `c`: 내 활동·빌드가 섞인 표본 제외). 계량 W 는 10분 이상 쌓인 그룹만 |
| 4 Netdata | CPU / 네트워크 / 디스크 / 메모리 / NVMe 온도(Netdata REST API; 웹 화면이 없는 빌드라 이 탭이 대신) |

- 그래프는 점자 문자(2×4 점) 면적 그래프(btop 과 같은 방식): 글자 칸보다 가로 2배·세로 4배 해상도이고, 세로 위치에 따라 초록→빨강 그라데이션. 표본 사이는 선형 보간(2분 넘게 끊긴 구간은 비움).
- 키: `1`~`4` 탭, `r` 구간, `g` 그룹, `c` 깨끗한 표본, `f5` 새로고침, `?`/`F1` 도움말, `q` 종료. 옵션 `--tab`, `--range`, `--interval`.
- **화면 갱신은 PSR 을 방해**하므로 기본 10초 주기이고 터미널이 포커스를 잃으면 갱신을 멈춘다. **측정 중에는 열어 두지 말 것.**
- 남은 시간은 `잔량 Wh ÷ 전력`(0%까지 쓴다고 가정). 잔량 Wh 는 누적 계량값(`q_uah`)×최근 방전 전압, 만충은 `charge_full`(마모 반영). 충전 중 전압은 방전 때보다 높아 Wh 를 부풀리므로 쓰지 않는다.
- 수집기가 새로 기록하는 필드: `dev.psr`(`mode`, `sink`), `pw.full_uah`. `observectl window --by psr` 로도 비교한다.

### Netdata 로의 미러링

수집기는 표본마다 숫자 일부를 Netdata statsd(`127.0.0.1:8125`)에 게이지로도 보낸다(`observe.*`: psys/pkg/core/uncore W, 방전·충전 전력, 잔량 %, state_low, psr_on, psr_sink_active, **ctxsw_top_all_threads_per_s(상위 프로세스의 모든 스레드 자발 전환 합)·ctxsw_all_per_s(시스템 전체 문맥 전환)**, **cpu_all_pct(전체 CPU 대비)**, 패키지 C-state pc2~pc10, s0ix. 2026-10-21 이전에 보낸 `wake_per_s`·`cpu_busy_pct`·`ctxsw_vol_top_per_s`(메인 스레드만) 차트는 이름이 달라 새 차트와 이어지지 않으며 7일 보관이 끝나면 사라진다. Netdata 에서는 `statsd_observe.<이름>_gauge` 차트로 보인다. **원본은 observectl(JSONL)** 이고 이쪽은 한쪽 방향 복사다 — 문자열·이벤트·표지·프로세스 상세·A/B 통계는 observectl 에만 있다. Netdata 쪽 이점은 시스템 지표(CPU·PSI·네트워크·디스크·온도)와 같은 시간축·같은 API 로 겹쳐 볼 수 있다는 것.

## `uikit` — 우리 TUI 공통 틀 (2026-10-21)

`mods/_data/_uikit/uikit.py`. displayui · clipui · notif_ui · powerui 가 복사해 쓰던 겉모습과 동작을 모았다: 검정 배경·둥근 회색 테두리(포커스 시 하늘색)·선택 줄 파랑·Footer 색(`BASE_CSS`), 대화상자 모양(`DIALOG_CSS`), 제목 달린 박스(`.box`, `uikit.box(위젯, 제목)`), `?`/F1 도움말(`HelpMixin`, 키 목록은 BINDINGS 에서 자동 생성), 포커스를 잃으면 갱신 정지(`PauseOnBlurMixin`). 각 앱은 `CSS = uikit.BASE_CSS + (앱 고유 규칙)` 로 쓴다. 배포 시 각 모듈이 `uikit.py` 를 같은 디렉터리에 복사하고, 소스 트리에서는 `../_uikit` 에서 가져온다. 시험: `_uikit/tests/test_uikit.py`.

## 스팬(구간)과 `observectl trace` (2026-10-21)

OTel 의 트레이스 개념만 빌린 것(OTel 을 넣거나 흉내 내는 게 아님): 작업 하나를 **시작·끝 이벤트 한 쌍(스팬)** 으로 묶고 부모-자식으로 연결해, 어디서 시간이 걸렸나와 **그 구간의 에너지**를 본다. 별도 서비스 없이 기존 이벤트 로그(JSONL)를 쓴다.

- 기록: 파이썬 `Events("comp").span("이름", level="info", k=v)`(`with` 문, `sp.set()` 으로 끝 이벤트에 속성 추가), 셸 `observe-emit span-run <comp> <이름> [k=v] -- 명령…`(종료 코드 그대로 전달, 인자는 기록하지 않고 실행 파일 이름만), `observe-emit span-begin/span-end`(셸 흐름 중간에 토큰으로).
- 연결: 같은 프로세스는 contextvar, **자식 프로세스는 환경변수 `OBSERVE_TRACE=trace:span`** 으로 부모를 이어받는다(안쪽 도구의 스팬이 바깥 스팬 아래로 붙음).
- 조회: `observectl trace [--since 1h] [--comp X] [--name 글자] [--min-ms N] [-n 5]` → 폭포(waterfall: 들여쓴 이름·소요·에너지·막대). `--by` → 이름별 요약(횟수·실패·소요 중앙값/95%/최대·평균/합 Wh). `--trace <id 앞부분>`.
- 에너지: 구간과 겹친 시간만큼 가중한 psys W 적분(표본 간격 30초). **구간이 짧거나 표본이 3개 미만이면 `~` 를 붙인 추정치.** 10분 이상이고 방전 중이면 누적 계량값(`q_uah`) 기준 Wh 도 함께 계산해 그쪽을 보여 준다. 더 촘촘히 보려면 `observectl on L1`(5초).
- 이미 심어 둔 곳: **nixup 전체**(`nixup:run`, 안쪽은 `log_exec` 의 Exec 시작/끝 쌍이 자동으로 자식 스팬 — nix build, 활성화, deadnix/statix 등), **displayui 적용**(`dispctl:tx.apply` 아래 build/migrate/apply_cfg/verify), **덮개 정책**(`lid-policy:apply`).
- 시험: `tests/test_trace.py`. 개인정보 원칙은 이벤트 로그와 같다(입력한 글자·URL·명령 인자 금지).

## eBPF 프리셋 `observectl bpf` (2026-10-21)

수집기(root)가 `bpftrace` 를 **요청할 때만 N초** 붙였다 뗀다(상시 계측 아님; 커널은 BTF·BPF JIT·kprobe/uprobe 지원). Wayland 가 없어도(VT 만 있어도) 동작한다. 프로그램은 코드에 고정된 프리셋이고 `--comm` 필터만 받는다(영숫자·`._-` 15자로 검증 — 프로그램 문자열 주입 방지). 개인정보 원칙: comm·pid·실행 파일 이름·횟수/바이트 합계만 본다(명령 인자·파일/패킷 내용·URL 안 봄).

| 프리셋 | 보는 것 | 쓰임 |
|---|---|---|
| `exec` | 프로세스 생성/종료 → **프로세스 스팬**(부모-자식, CPU 시간) | 누가 프로세스를 자주 만드나. 결과를 이벤트 로그에 적어 `observectl trace --comp bpf` 로 폭포·에너지를 본다 |
| `wake` | 깨우는 쪽 → 깨어나는 쪽 comm 쌍(sched_waking) | 전력의 원인 추적(기존 `wakers` 의 eBPF 판) |
| `profile` | 99Hz CPU 샘플링: 프로세스별 CPU %, 가장 많이 걸린 커널/사용자 맨 위 함수 | JFR 의 가벼운 버전 |
| `psr` | drm atomic 커밋을 일으킨 comm 별 횟수 + i915 PSR flush/exit/activate | **PSR 이 왜 풀리나**(화면을 계속 그리는 프로세스 찾기) |
| `io` | 블록 입출력 comm 별 횟수·바이트 | 디스크 깨움 |
| `net` | TCP/UDP 송수신 호출 comm 별 횟수 | 네트워크로 깨우는 프로세스 |

- 사용: `observectl bpf <프리셋> [초=10] [--comm X] [-n 12]`. 시험: `tests/test_bpf.py`(가짜 bpftrace 로 파서·요약·job 검증).
- 의존: nixpkgs `bpftrace`(clang 라이브러리 때문에 풀면 약 1 GiB, 내려받기 약 165 MB). 수집기 서비스 환경변수 `OBSERVE_BPFTRACE` 로 지정.
- 안전: `observe-emit span-run` 은 신호를 자식에게 맡긴다(Ctrl-C 를 받아도 자식을 강제로 죽이지 않아 nixup 의 정리/잠금 해제가 실행됨). `nixup`·`log_exec` 계측은 `observe-emit span-probe` 가 통과할 때만 켜진다(옛 observe-emit 이 설치된 상태에서 nixup 이 막히지 않게).

## 창·포커스 구간 `observe-focus` (2026-10-21)

앱을 수정하지 않고 "어느 앱을 쓰던 구간인가"를 스팬으로 남긴다. Hyprland 이벤트 소켓(`.socket2.sock`)의 `openwindow`/`closewindow`/`activewindowv2` 를 읽어:
- `windows:window:<class>` — 창이 열려 있던 동안(루트, 속성 ws)
- `windows:focus:<class>` — 그 창이 포커스였던 동안(창 스팬의 자식)

조회: `observectl trace --comp windows --since 1h` (폭포), `--by` (앱별: 횟수·포커스 시간 중앙값/95%/최대·평균/합 Wh).
- **창 제목은 기록하지 않는다**(메일 제목·URL 이 들어갈 수 있음). class(앱 이름)와 작업공간 이름만.
- 사용자 서비스 `observe-focus`(graphical-session 에 묶임, 이벤트가 올 때만 깨어남, 재시작 정책 없음 — Hyprland 가 끝나면 열린 구간을 닫고 종료). 서비스 시작 전부터 있던 창은 시작 시점(관측 시작)부터로 기록된다.
- **에너지는 30초 표본에 걸친 적분이라 포커스가 몇 초뿐인 구간은 `~` 추정치**다(몇 분 이상 쓴 구간에서 의미). 앱별 합계(`--by`)가 더 믿을 만하다. 정밀하게 보려면 `observectl on L1`(5초).
- 시험: `tests/test_focus.py`(상태 기계·소켓·SIGTERM 정리).

## 필드 이름과 단위 — 표본 형식 v2 (2026-10-21)

같은 말이 도구마다 다른 양을 가리켜 생긴 오해(예: `ps` 의 %CPU 는 시작 이후 누적 평균)를 막으려고 **이름에 단위·범위를 넣었다.** 옛 이름과 뜻은 `power-evidence.md` 의 "용어·단위 정정표"(L1~L8)에 있다.

| 옛 이름(v1) | 새 이름(v2) | 뜻 |
|---|---|---|
| `pw.batt_w` | `pw.batt_vi_w` | 배터리 전압×전류의 **순간** 절댓값(방전 중에만 방전 전력, 충전 중엔 충전 전력) |
| `irq.cpu_busy_pct` | `irq.cpu_all_pct` | **전체 CPU 대비** 사용률(100 = 모든 CPU 가 계속 일함) |
| `proc[].cpu`, `thr[].cpu` | `cpu_core_pct` | **코어 1개 = 100%** (여러 코어를 쓰면 100 을 넘음) |
| `proc[].wake`, `thr[].wake` | `ctxsw_vol_s` | **자발적 문맥 전환/s**(스스로 잠든 횟수). 시스템 전체 깨움(`sched_waking`)이 아니다. **proc 행은 v3 부터 모든 스레드 합**(스레드 1개 프로세스 외에는 `task/*/status` 를 합산), thr 행은 스레드 단위 |
| (v1·v2 의) `proc[].ctxsw_vol_s` | `ctxsw_vol_leader_s` | **옛 값 — `/proc/<pid>/status` 의 메인 스레드만**이라 멀티스레드 프로세스를 크게 과소 집계(전체 합의 약 27%만 보임). 합산·순위·비교에 쓰지 않는다(`window`/`top`/powerui 는 제외하고 안내) |
| (없음) `irq.ctxt_s` | 그대로 | 시스템 전체 문맥 전환/s(비자발 포함, `/proc/stat` ctxt) |
| `state` = low/high | 그대로 | **패키지 pc10 ≥ 5%(깊은 절전 진입) 여부**이지 전력 높낮이가 아님. 화면에는 `low(깊은 절전)` 처럼 뜻을 함께 쓴다 |

- 새 표본은 `v: 4`(v2 는 이름 정리, **v3 는 proc 행 `ctxsw_vol_s` 를 모든 스레드 합으로 정정**, **v4 는 `apps` 추가**). v3→v4 는 값의 뜻이 바뀌지 않아 legacy 가 아니다(apps 가 없을 뿐). **옛 표본(v 없음·v2)은 파일을 고쳐 쓰지 않고 읽을 때 새 이름으로 바꾸며 `legacy: true` 를 단다**(`observe_core.normalize_sample`; `iter_jsonl` 과 powerui 의 `Store` 가 적용). `observectl window` 와 powerui 상태줄은 옛 형식 표본이 섞이면 개수를 알려 준다. 보관 기간이 지나면 옛 표본은 사라진다.
- 화면 열 이름: `observectl window` 는 `V×I`·`상위전환/s`(**저장된 상위 프로세스 최대 16행의 합 — 시스템 전체가 아님**)·`전체CPU%`, `observectl top` 은 `CPU(코어1개=100%)`·`자발전환/s`. powerui 현황은 "전환 시스템 전체 / 상위 프로세스(합계 아님)" 와 "CPU 전체 대비" 를 따로 보여 준다.
- 옵션 호환: `observectl top --by wake` 와 `observectl ab --metric batt_w` 는 새 이름의 옛 별칭으로 계속 받는다(안내를 출력).
- "지금 CPU" 를 볼 때는 `ps` 의 %CPU(프로세스 시작 이후 누적 평균)가 아니라 `observectl top --since 1m`(구간 평균) 이나 `observectl bpf profile`(99Hz 표본)을 쓴다.

## 종합 조회 `observectl explain`과 Netdata 어댑터 (2026-10-21)

**구조 결정**: observectl 이 분석의 입구이고, Netdata 는 **켜져 있을 때만 쓰는 내부 어댑터**(`observe_netdata.py`)다. Netdata 를 배터리에서 끄는 정책(#2·#58·T3)과 양립하도록, 꺼져 있으면 해당 항목을 **"관측 공백"**(0 이 아님)으로 표시하고 observectl 만으로 계속 분석한다. 1초 간격 전체 수집을 observectl 에 다시 만들지 않는다(파이썬으로 1초마다 전 프로세스를 읽으면 CPU 약 5%). **언어는 정해져 있지 않다** — 가장 강한 제로베이스 후보인 커널 안 eBPF 집계도 실험했다(장부 #61): 정확성은 `/proc` 모든 스레드 합과 99% 일치하지만 bpftrace 구현은 `sched_switch` 호출당 약 5.9 µs 라 지금 부하에서 코어의 1.8%, 부하에 비례해 커서 상시용으로는 보류(libbpf 로 다시 만들면 가능 — T23). 대신 **Netdata 가 틀린 부분(앱별 자발적 전환: 메인 스레드만 읽음)은 우리가 정확하게 직접 구현**했다(수집기 v3, 30초 간격 +0.17% CPU).

- `observectl explain [--since 30m | --at HH:MM --span 300] [--baseline prev|none|시작..끝] [--no-netdata] [--json]` — 한 구간을 **기준 구간(기본: 바로 앞 같은 길이)과 비교**해 한 화면에: ① 요약(상태 low/high·PSR·덮개·전원) ② 전력 4지표(psys·패키지·순간 V×I·누적 계량, 신뢰 낮은 값은 표시하고 순위에서 제외, Netdata 1초 값 병기) ③ 시스템 활동(전체 CPU·문맥 전환·인터럽트, Netdata 가 있으면 네트워크·디스크·온도·프로세스 생성) ④ 프로세스(observectl 저장분 + Netdata 앱 그룹 CPU) ⑤ 포커스한 앱·열린 구간과 에너지 ⑥ **기준 대비 달라진 것의 순위(상관일 뿐 인과가 아님)** ⑦ 한계. 같은 계산을 powerui **5 원인 탭**(`w` 로 구간 15분/30분/1시간/3시간)이 쓴다.
- `observectl window` 는 Netdata 가 있으면 표 아래에 네트워크·디스크·NVMe 온도를 같은 그룹으로 병기한다(`--no-netdata` 로 뺌). `observectl nd charts [이름조각]` 으로 차트(이름·단위·제목)를 찾고 `observectl nd get <차트> --since 30m` 으로 값을 본다(공백은 '공백'으로 표시).
- `observectl query <신호…> [--since 1h] [--step 5m | --by state] [--agg mean|min|max|p50|p95|sum|count]` — 범용 조회. 신호는 별칭(`psys pkg vi core uncore pc8 pc10 cpu_all`)·표본 경로(`pw.psys_w`)·`app:<앱>.cpu|ctxsw`·`proc:<comm>.cpu|ctxsw`·`nd:<Netdata 신호>`(예: `nd:net_rx_kbps`). `vi` 는 방전 중 표본만, 옛 표본의 프로세스 전환 값(메인 스레드만)은 쓰지 않는다, Netdata 가 꺼져 있던 구간은 '-'(관측 공백). 예: `observectl query psys app:claude.cpu nd:net_rx_kbps --since 2h --step 10m`.
- `observectl nd defs|stats|apps` — 어댑터가 가져오는 신호의 정의·구간 평균·앱 그룹 CPU. 정의는 실제 Netdata API 메타데이터와 교차 검증했다(예: `app.*_cpu_utilization` 제목 "100% = 1 core" 와 수집기 값이 일치).
- Netdata 에 **있고 observectl 에 없는 것**: 1초 해상도(RAPL·전압·전류·CPU·인터럽트), 앱 그룹 88개 전체의 CPU, 네트워크·디스크·온도. **observectl 에 있고 Netdata 에 없는 것**: 패키지 C-state(MSR), PSR 상태, 표지·스팬·포커스, 누적 계량, eBPF 프리셋, A/B 통계.
- **한계(그대로 둠)**: 표본 30초라 짧은 사건은 흐림, 저장하는 프로세스는 상위 16행(전환 커버리지를 `explain` 이 표시), 프로세스별 전력은 측정이 아니라 CPU 시간 기반 대용치, 포커스 구간 에너지는 시간 분배일 뿐 원인 귀속이 아님.

## 단계형 정밀 모드 `observectl ebpf` (2026-10-21)

기본 수집(L0, 30초, 스레드 정확, 코어 약 0.5%)은 그대로 두고, **필요한 만큼만 시간 제한을 걸어 정밀도를 올리는** 모드. 수집기가 bpftrace 를 자식으로 띄워 30초마다 프로세스(tgid)별 집계를 표본의 `ebpf` 필드에 합친다(`explain` 의 "프로세스·앱" 섹션에 정밀 표로 나옴).

| 단계 | 방식 | 정확성(실측) | 비용(코어 1개) |
|---|---|---|---|
| `sample` | 약 18.6Hz(53,711µs, 비조화 주기) CPU 점유 샘플링 | 통계적 추정: 같은 이름으로 합쳐 기본 수집과 비교한 전체 중앙값 0.99(netdata 1.09·electron 0.93). 두 측정의 30초 창이 어긋나 개별 간격은 ±큼 | **0.12%**, 부하와 무관 |
| `counts` | `sched_switch` 전환 합계(맵 1회) | 프로세스별 총 전환 98% | 0.62%, 전환 수에 비례 |
| `full` | 자발·비자발·on-CPU 시간 | 자발 전환 99%, CPU 시간 101% | 1.8%, 전환 수에 비례 |

- 사용: `observectl ebpf on <sample|counts|full> [--for 10m]`(수집이 켜져 있어야 함), `off`, `status`, `tiers`(단계표).
- 안전장치: 제한 시간(기본 10분, 최대 60분)이 지나면 자동 종료 · `counts`/`full` 은 시스템 전환이 초당 15,000 을 넘으면 스스로 멈춤(비용이 부하에 비례) · 멈춘 이유는 표본의 `ebpf_stopped` 와 `status` 에 남음 · 수집기가 끝나면 자식도 끝남.
- 권장 쓰임: `sample`(0.12%)은 분석 구간 내내 켜 둘 만한 가장 싼 단계, `full` 은 "누가 깨우나/얼마나 쓰나"를 정확히 봐야 하는 몇 분짜리 구간. 상시 켜 두지는 않는다(장부 #61).
- **정수 Hz 샘플링은 쓰지 않는다**: 19Hz 로 처음 만들었더니 1초 주기로 일하는 Netdata 와 위상이 고정돼 기본 수집의 약 3.2배(2.9~3.4배)로 과대 추정됐다(장부 #61). 주기를 1/(18+0.618…)초(53,711µs)로 잡아 위상이 골고루 이동하게 한 뒤 1.09배. `observectl bpf profile` 도 99Hz → 10,038µs 로 같은 이유로 고쳤다.
- 한계: 맵 집계라 30초 안의 순서는 모름, `comm` 은 해석 시점의 `/proc` 이름(끝난 프로세스는 `?`), 시험은 가짜 bpftrace 로 하고 실제 비용은 `bpftool prog show`(`kernel.bpf_stats_enabled`)로 잰다.

## 앱 단위 집계 `apps` (표본 형식 v4, 2026-10-21)

Netdata 의 "앱 그룹" 개념을 우리 시스템에 맞게 가져왔다(`observe_apps.py`). 옛 `proc` 행은 표본마다 **상위 16행만** 저장해 전체 CPU 의 약 60%·문맥 전환의 약 34%만 담았다(긴 꼬리가 빠짐). 새 `apps` 필드는 **전체 프로세스를 앱으로 묶은 합계 + `(기타)` 한 행**이라 합계가 빠짐없이 보존된다(커버리지 100%).

- 행: `{app, n(프로세스 수), cpu_core_pct(코어 1개=100%, 모든 스레드), ctxsw_vol_s(모든 스레드 자발 전환/s), rss_mb}` — 상위 24개 + `(기타)`.
- 묶는 규칙: 커널 스레드 → `kernel` · Nix 래퍼 이름 정리(`.claude-wrapped` → `claude`) · 알려 둔 계열(netdata+플러그인, vivaldi+도우미, nix 계열, hyprland 계열, kitty, tailscaled, waybar) · **Electron 은 맨 위 프로세스의 `app.asar` 경로(Nix 저장소 이름)로 앱을 정함**(예: `bitwarden-desktop`; 도우미 zygote·renderer·gpu 가 같은 앱으로 묶임) · 그 밖에는 정리한 이름 그대로. 명령줄은 asar 경로만 보고 저장하지 않는다. 실행 파일을 못 읽는 보호된 프로세스는 comm 으로 보강한다.
- 사용: `observectl top --by app`, `observectl explain` 의 "프로세스·앱" 섹션(앱 단위 표 + 기준 대비 변화 순위는 앱 CPU 로). v3 이하 표본에는 `apps` 가 없어 옛 표(상위 16행)로 대체한다.
- 한계: 규칙 표에 없는 앱은 정리한 프로세스 이름으로 나온다(필요하면 `observe_apps.RULES` 에 추가). 맵이 아니라 30초 구간의 합계라 짧은 사건은 흐림.
