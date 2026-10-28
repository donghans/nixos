# 외부 키보드가 있으면 내장 키보드를 끄기 (extkbd)

**상태 (2026-10-27): 코드와 자동 시험은 작성됨, 노트북에는 아직 배포 전.** 「구현 결과」(§6)에 만든 것과 아직 확인하지 못한 것을 구분해 적었다. 이 문서는 "무엇을 알아냈고, 무엇을 하기로 했고, 무엇이 아직 모르는 것인지"를 남긴다. 「이 세션」은 이 문서를 쓴 Claude Code 세션(2026-10-27, 사용자와 대화하며 노트북에 ssh 로 접속해 확인)을 뜻한다.

구현이 문서와 어긋난 곳은 §2 의 F4 하나다(구현 중 실기 시험에서 발견·정정, §6 참고).

## 1. 목적과 배경 (사용자 요구)
- 대상은 노트북 `msi-summit-me`(MSI Summit E16 Flip, 360도 힌지 2-in-1)뿐이다. 데스크톱(`beelink-ser7-co`) 등 다른 호스트는 대상이 아니다.
- 사용자의 내장 키보드는 고장 상태라(키 몇 개가 자꾸 안 눌림. 이력은 `mods/_tools/desktop/posture/README.md` 의 「후속 조사 (2026-10-20 새벽)」 4번) 외부 키보드를 쓴다. 외부 키보드를 **내장 키보드 위에 얹어 두고** 쓰는 일이 많아서, 이때 내장 키보드 키가 눌려 오입력되는 것을 막고 싶다.
- 요구: 외부 키보드(유선 USB, 2.4G 무선 수신기, 블루투스)가 **연결되면** 내장 키보드를 비활성화하고, **연결이 끊기면** 다시 활성화한다.
- 이 사용자는 블루투스 키보드 `AULA-F87Pro 5.0` 을 이 노트북에 이미 연결해 둔 상태다.

## 2. 이 세션이 알아낸 사실 (일어난 일 — 계획이 기대는 근거)
등급은 `직접확인`(이 세션이 명령/파일로 확인), `미재확인`(보고·문서를 그대로 실음).

| # | 사실 | 등급 / 출처 |
|---|---|---|
| F1 | 내장 키보드는 `AT Translated Set 2 keyboard`(PS/2, `ID_BUS=i8042`, `ID_INPUT_KEYBOARD=1`). 노트북에서 `udevadm info /dev/input/event2` 의 `ID_BUS=i8042`. | 직접확인 (노트북 ssh) |
| F2 | 연결된 블루투스 키보드는 커널 `uhid` 가상 장치로 나타나며 `ID_INPUT_KEYBOARD=1`, `ID_BUS=bluetooth`. 같은 기기가 키보드 외에 마우스 노드(`ID_INPUT_MOUSE=1`)와 속성 없는 노드를 더 노출한다 — 키보드 판정은 `ID_INPUT_KEYBOARD=1` 인 노드만 따르면 된다. | 직접확인 |
| F3 | udev 가 입력 노드의 HID 능력을 보고 `ID_INPUT_KEYBOARD`·`ID_BUS` 를 붙인다. 판정은 이 두 속성으로 할 수 있다(별도 HID 디스크립터 파싱 불필요). 터치스크린/터치패드/전원·덮개 스위치/WMI 핫키는 `ID_INPUT_KEYBOARD` 가 없다. | 직접확인 — **다만 이 노트북에 그때 연결돼 있던 노드들에 한정**(노트북의 모든 `/dev/input/event*` 속성을 훑음). 다른 USB 키보드·수신기에서도 같은지는 시험하지 않았다(Q3·Q4) |
| F4 | `udevadm info -q property /dev/input/event*` 를 한 번 부르면 모든 입력 노드의 속성이 나오고 약 0.01~0.02초 걸린다(`--export-db` 는 0.35초라 쓰지 않는다). **장치 사이에 빈 줄이 없다** — 장치마다 첫 줄이 `DEVPATH=` 이라 그 줄에서 새 장치가 시작된다(systemd 260.1, 노트북). *이 문서의 초안은 "빈 줄로 구분"이라고 잘못 적었고, 가짜 출력으로 만든 자동 시험도 그 오류를 그대로 따라서 통과했다. 실제 노트북에서 `extkbd status` 를 돌려 보고서야 속성이 장치 사이에 섞이는 것을 발견해 고쳤다.* | 직접확인 (노트북에서 실행한 출력으로 정정) |
| F5 | 블루투스 장치의 MAC 은 입력 노드의 `uniq`(예: `/sys/class/input/input40/uniq` = `d6:f0:27:b9:65:70`)이고, BlueZ 의 `Connected` 상태는 `busctl --system call org.bluez / org.freedesktop.DBus.ObjectManager GetManagedObjects` 로 일반 사용자가 읽을 수 있다(장치별 `Address`·`Connected`). | 직접확인 (`bluetoothctl info` 로 `Connected: yes` 도 확인) |
| F6 | 일반 사용자의 `busctl monitor` 는 `BecomeMonitor ... Access denied` 로 실패한다(직접확인). `gdbus monitor --system --dest org.bluez`(nixpkgs `glib`; 노트북에는 `gdbus` 가 없어 `nix-shell -p glib` 로 실행)는 일반 사용자로 시작되고 `The name org.bluez is owned by :1.7` 을 출력했다(직접확인). 대상 이름이 없을 때(`--dest org.nonexistent.Foo`)는 종료하지 않고 "does not have an owner" 를 출력하며 기다린다(직접확인, 데스크톱). **실제 BlueZ 신호(`Connected` 변화)가 이 방식으로 들어오는지는 아직 확인하지 못했다**(Q5). `udevadm monitor` 도 일반 사용자로 된다(기존 `devwatch.py` 가 씀, 코드 읽음). | 직접확인(시작·권한·이름 대기) / **미확인(신호 수신)** |
| F7 | 이미 내장 키보드를 끄는 정책이 있다: `mods/gui/base/core.bind.hwctl.nix` 의 `hypr-input-policy`(133행~). 텐트/태블릿 모드(139행 `tent\|tablet) kb=false; ...`)에서 키보드를 끄고 노트북 모드(141행 `kb=true`)에서 켠다. 끄는 방법은 Hyprland 의 `hl.device({name=..., enabled=...})`(166행 `set_enabled`)이며 **대상은 호스트가 `internalKeyboardName` 으로 지정한 키보드 하나**(옵션 선언은 같은 파일 285행, msi 의 지정은 `hosts/msi-summit-me.nix:335`)뿐이다. (줄 번호는 이 변경 전 기준. `set_enabled` 는 149행에서 정의하고 166행에서 호출한다.) 지정이 없는 호스트에서는 키보드를 건드리지 않는다. | 직접확인 (파일 읽음) |
| F8 | 그 정책은 이벤트를 놓쳐도 아무 때나 실행하면 현재 상태에 맞춰지는 **수준 기반·멱등** 소비자다(상태 파일과 `posture` CLI 값만 읽어 장치를 맞추는 코드를 읽고 낸 판단이며, `mods/_tools/desktop/posture/README.md` 에 그렇게 명시돼 있지는 않다). 힌지 모드 변화(`posture-apply`), 로그인, Hyprland reload 때 실행된다(`core.posture.nix`: `hyprland.start`, `config.reloaded`, `posture-apply.path`). | 직접확인(실행 시점) / 코드 읽고 추론(멱등성) |
| F9 | 사용자 서비스 환경에는 `HYPRLAND_INSTANCE_SIGNATURE`·`WAYLAND_DISPLAY` 가 올라와 있어서(노트북 `systemctl --user show-environment`) 서비스에서 `hyprctl` 을 부를 수 있다. | 직접확인 |
| F10 | 정책 `--print` 의 출력은 `모드 각도 키보드 터치패드 터치스크린` 5필드이고 두 곳이 파싱한다: 토글(99행, `cut -d' ' -f4/5`)과 메뉴(208행, `read -r mode angle kb tp ts`). 필드를 **뒤에 덧붙이면 208행의 마지막 변수 `ts` 에 합쳐져 깨진다**. | 직접확인 |
| F11 | 이 노트북은 전력 시험을 자주 한다(ctx 장부 `note power-evidence-ledger`). 상시 폴링·주기 깨어남을 새로 넣으면 안 된다 — 이벤트 구동이어야 한다. | 미재확인 (사용자 CLAUDE.md 의 관측·전력 지침과 ctx 장부 제목에서 추정. 상시 폴링 금지는 이 세션의 설계 판단) |

## 3. 아직 모르는 것 (열린 질문 — 구현 후 관찰로 닫는다)
- **Q1. 블루투스 키보드가 잠들거나(자동 절전) 전원이 꺼질 때** `uhid` 입력 장치가 사라지는가, BlueZ `Connected` 가 `no` 가 되는가? 이 세션에서 시험하려 했으나 사용자가 관찰 중 키보드를 써서 **시험하지 못했다.** 계획은 어느 쪽이어도 안전하도록 짰다(§4 의 판정은 `Connected` 를 본다). 구현 후 사용자가 일상에서 (1) 전원 끄기, (2) 방치로 자동 절전을 겪으며 `extkbd status` 와 저널로 확인한다.
- **Q2. 잠든 키보드가 `Connected=yes` 로 남는 경우**: 내장 키보드가 꺼진 채 외부 키보드도 반응하지 않는 순간이 생긴다. 블루투스 키보드는 아무 키나 누르면 깨어나므로 사용자 입력 수단은 유지되지만, 이 가정은 **미확인**이다. Q1 관찰에서 같이 확인한다.
- **Q5. BlueZ 신호 수신**: `gdbus monitor` 가 블루투스 키보드의 `Connected` 변화를 실제로 알려 주는지(F6 의 미확인 부분). 안 알려 주면 블루투스 연결이 끊겨도 정책이 다시 돌지 않는다(다음 입력 장치 이벤트·힌지 변화·로그인·reload 때 맞춰짐). 구현 후 `journalctl --user -t hypr-input-policy` 로 키보드 전원을 껐다 켤 때 정책이 도는지 본다.
- **Q3. 2.4G 수신기**: 수신기는 키보드가 꺼져 있어도 꽂혀 있는 한 `ID_INPUT_KEYBOARD=1` 노드로 남을 수 있다(이 세션의 데스크톱에서 `Nordic 2.4G Wireless Receiver` 가 키보드 노드로 보임: `/proc/bus/input/devices`, 직접확인. 단 이 노트북에서는 시험 안 함). 즉 "수신기 있음 = 키보드 있음"으로 판정하게 된다. 사용자 결정: **그대로 포함**하고, 키보드가 안 먹히면 수신기를 뽑는다(뽑으면 제거 이벤트로 내장 키보드가 켜진다).
- **Q4. 마우스 전용 수신기·키보드 기능이 있는 마우스**를 꽂아도 `ID_INPUT_KEYBOARD=1` 이 붙으면 내장 키보드가 꺼진다. 실제로 일어나는지는 시험하지 않았다. 일어나면 `extkbd status` 로 원인 장치를 본다.

## 4. 하기로 한 일 (설계)

### 4-1. 판정: "외부 키보드가 있는가"
입력 노드(`/dev/input/event*`) 중 아래를 모두 만족하는 것이 하나라도 있으면 "있음".
1. `ID_INPUT_KEYBOARD=1`
2. `ID_BUS` 가 `usb` 또는 `bluetooth` (내장 `i8042`, 플랫폼/ACPI/가상은 제외)
3. 블루투스(`ID_BUS=bluetooth`)면 BlueZ 에서 그 MAC(노드의 `uniq`, 대문자 변환)의 `Connected` 가 true 로 **확인**돼야 한다. 확인하지 못하면(BlueZ 응답 없음, `uniq` 없음, 장치 목록에 없음) **없음으로 본다** — 판정이 불확실할 때는 내장 키보드를 켜 둔다(키보드가 모두 꺼진 상태가 가장 나쁜 결과이므로).
4. 노드의 sysfs 경로가 지금 존재해야 한다(제거 직후의 낡은 정보 배제).

판정 코드는 새로 만든 `mods/_tools/desktop/external-keyboard/extkbd.py`(표준 라이브러리만; 시험 `mods/_tools/desktop/external-keyboard/tests/test_extkbd.py`). 명령:
- `extkbd present` — 있으면 종료 코드 0, 없으면 1. 정책이 부른다. **정책은 0 일 때만 "있음"으로 보고, 어떤 이유의 실패(예외·시간 초과·실행 파일 없음·사용법 오류 2)든 "없음"으로 본다**(내장 키보드를 켜 둠).
- `extkbd status` — 노드별 판정과 이유(사람이 읽는 표). 문제 진단용.
- `extkbd watch` — 감시 데몬(§4-3).

### 4-2. 적용: 기존 `hypr-input-policy` 에 얹는다
- 노트북 모드에서 `kb=true` 이던 것을 "외부 키보드가 없을 때만 true" 로 바꾼다(`tent|tablet` 은 이미 false). 새 장치 제어 코드를 만들지 않고 기존 `set_enabled` 를 그대로 쓴다 → 끄는 대상은 여전히 `internalKeyboardName` 이 지정된 키보드뿐이라 **다른 호스트와 지정 없는 호스트에서는 아무 일도 일어나지 않는다**("노트북 한정" 요구 충족).
- `--print` 출력에 필드를 덧붙이지 않고(F10), 소비자 두 곳을 바꾸지 않아도 되게 **키보드 필드(3번째) 값이 외부 키보드 영향을 이미 반영**하도록 한다. 즉 `--print` 의 `kb` 가 곧 "내장 키보드가 켜져야 하는가"이다. 소비자 변경은 필요 없다.
- 외부 키보드 유무가 바뀐 순간에만 알림(낮은 긴급도)을 낸다. 마지막 상태는 `~/.local/state/hypr/extkbd_last` 에 기록한다(기존 `hinge_last_mode` 와 같은 방식). 처음 실행은 조용히. 기존 모드 알림 문구(노트북 모드면 "키보드 켬")는 외부 키보드가 있을 때 사실과 어긋나므로 키보드가 꺼진 경우의 문구를 따로 둔다.
- 저널 한 줄(`hypr-input-policy`)에 `ext=true|false` 를 추가한다.
- **동시 실행 직렬화(flock)**: 감시 서비스와 `posture-apply` 가 같은 시점에 정책을 돌리면, 판정(읽기)을 먼저 한 쪽이 낡은 값으로 나중에 적용해 덮어쓸 수 있다. 판정부터 적용까지를 `~/.local/state/hypr/policy.lock` 의 `flock`(최대 30초 대기, 못 잡으면 그냥 진행)으로 감싼다. `--print` 는 읽기 전용이라 잠그지 않는다. 상태 파일(`hinge_last_mode`, `extkbd_last`)도 이 잠금 안에서만 쓰여 알림이 중복·누락되지 않는다.
- `--print`(토글·메뉴가 부름)도 이제 `extkbd present` 를 부르므로 호출당 비용이 늘어난다(파이썬 시작 + `udevadm` + 블루투스가 있으면 `busctl`; 약 0.1초대로 추정, 측정하지 않음).

### 4-3. 감시: 이벤트 구동 사용자 서비스 `extkbd-watch`
- 자식 프로세스 둘을 띄우고 출력을 `select` 로 기다린다(폴링·타이머 없음, F11).
  - `udevadm monitor --udev --subsystem-match=input` : 입력 장치 추가/제거 줄이 오면 후보.
  - `gdbus monitor --system --dest org.bluez` : 줄에 `Connected` 가 있으면 후보(F6; `glib` 패키지는 nix 가 경로를 고정).
- 후보 이벤트가 오면 **1초 디바운스** 후 `hypr-input-policy` 를 한 번 실행한다(버스트·재연결 때 여러 번 도는 것 방지). 정책은 멱등이라 중복 실행돼도 안전하다(F8).
- 시작할 때 한 번 실행한다. 자식이 하나라도 종료하면 데몬도 비정상 종료하고 systemd 가 다시 띄운다(`Restart=on-failure`, 시작 때 다시 실행하므로 놓친 이벤트가 복구됨).
- 설치 조건: 서비스에 **두 조건을 직접 건다** — `config.workspace.type == "laptop"` 그리고 `internalKeyboardName != null`. (기존 `posture.consumers` 등록부(245행 부근)에는 앞 조건만 있고, 뒤 조건은 정책 안의 `set_enabled` 호출(166행)에만 있다.)
- **기동 시점**: `graphical-session.target` 뒤에 시작하고(`After`/`PartOf`/`WantedBy` 모두 이 타깃; 같은 패턴이 `vkb.nix:37-44` 의 wvkbd 서비스에 있다), 그래야 `HYPRLAND_INSTANCE_SIGNATURE` 가 서비스 환경에 올라온 뒤에 정책의 `hyprctl` 이 돈다. (`default.target` 에 걸면 환경이 없어 시작 때 한 번 도는 정책이 조용히 아무것도 못 한다. 환경 변수는 `UWSM_WAIT_VARNAMES=HYPRLAND_INSTANCE_SIGNATURE` 로 보아 Hyprland 가 올라온 뒤에 들어온다 — 이 대응 관계는 노트북의 `systemctl --user show-environment` 출력에서 읽은 것이고 uwsm 문서·코드로 확인하지는 않았다.)
- **재시작**: `Restart=on-failure`, `RestartSec=5`, `StartLimitIntervalSec=0`(시작 제한 없음). `gdbus monitor` 는 BlueZ 가 없어도 종료하지 않고 기다리므로(F6) 블루투스가 꺼진 기기에서 재시작 루프가 되지 않을 것으로 본다.
- 안전 속성: ① 판정 불확실 → 켬 ② 서비스가 죽어도 정책의 마지막 상태는 유지되지만, 다음 로그인/reload/힌지 변화 때 `posture-apply` 가 같은 정책으로 다시 맞춘다 ③ 블루투스 키보드가 잠들었는데 `Connected` 가 `yes` 로 남는 경우 내장 키보드가 꺼진 채 입력이 없을 수 있다(Q2). 이때는 외부 키보드의 아무 키를 눌러 깨우는 것이 복구 수단이라고 가정하지만 **확인하지 못했다**. ④ 비상 복구: 외부 키보드 연결을 끊거나 수신기를 뽑는다, `systemctl --user stop extkbd-watch` 후 `hypr-input-policy`, 또는 재로그인(Hyprland 장치 enable 은 런타임 상태라 재시작하면 초기화).

### 4-4. 하지 않는 것 (범위 밖)
- 커널 수준 비활성화(`/sys/class/input/inputN/inhibited`)는 쓰지 않는다. 기술적으로 가능함은 확인했지만(이 노트북에 `inhibited` 파일 있음, 직접확인) 이 저장소에는 이미 Hyprland 장치 enable 정책이 있고, 두 메커니즘이 서로 모르면 한쪽이 켜고 다른 쪽이 꺼 둔 상태가 생길 수 있다.
- TTY 콘솔·로그인 화면(greeter)의 내장 키보드는 그대로 켜져 있다(Hyprland 안에서만 끔). 잠금 화면(hyprlock)은 Hyprland 안이라 영향 받는다.
- 외부 키보드가 연결된 동안 가상 키보드(wvkbd) 자동 숨김은 이번 범위가 아니다.
- 다중 외부 키보드 중 어느 것이 "실제로 쓰이는지" 판별하지 않는다(하나라도 있으면 있음).

## 5. 검증 계획
1. **자동 시험** `mods/_tools/desktop/external-keyboard/tests/test_extkbd.py`(기존 `mods/_tools/_lib/testkit/harness.py` 의 `checker()` 로 `check(이름, 조건)`·`finish(제목)` 형식; `mods/_tools/run-tests.sh` 의 목록에 `extkbd` 로 등록): 속성 블록 파싱, 판정 규칙(i8042 제외, 가상/ACPI 제외, USB/블루투스 포함, 블루투스 Connected 미확인 → 없음, `uniq` 없음 → 없음, 제거된 노드 무시), `udevadm`/BlueZ 를 가짜 실행 파일로 대체한 `present`·`status`, 감시 데몬(가짜 이벤트 줄 → 디바운스 후 정책 1회 실행, 자식 종료 시 데몬 종료).
2. **Nix 평가**: `nixup check` 는 저장소 전체에 `statix fix`/`alejandra` 를 돌려 파일을 고치므로 쓰지 않았다. 대신 `nixup` 이 만드는 빌드 사본을 손으로 재현했다 — 임시 디렉터리에 `core/ hosts/ mods/` 복사, `core/flake.nix` 를 루트에 복사, `python3 -B core/scripts/nixup.task-resolve.py <저장소> <json 디렉터리>` 로 만든 `resolved.json`·`presets.json` 복사, 노트북이 쓰는 `.locks/_rolling.lock` 을 `flake.lock` 으로 복사(다른 lock 이면 무관한 `llm-cli.nix` 오류가 났다), 노트북의 `.build/.env`·`hardware.nix` 복사. 그 뒤 `nix eval "path:<디렉터리>#homeConfigurations.\"donghans@msi-summit-me\".activationPackage" --apply 'p: p.drvPath' --allow-import-from-derivation`.
   `extkbd-watch` 서비스가 msi 에만 생기는지 확인(`donghans@beelink-ser7-co` 에는 없음), 생성된 `hypr-input-policy`·`extkbd` 스크립트를 빌드해 `bash -n` 으로 문법 확인.
3. **실기(노트북)**: 배포는 이 노트북이 **스탠드얼론**(`hosts/msi-summit-me.toml` 에 `[deploy]` 없음, 직접확인)이므로 커밋·push 후 노트북에서 `git pull && nixup` 한다. 확인할 것: (a) 지금 연결된 AULA 키보드로 `extkbd status` 가 "있음", 내장 키보드 입력이 막힘(`hyprctl devices` 의 `enabled`·실제 입력), (b) 블루투스 해제 후 내장 키보드 복원, (c) 재연결 후 다시 꺼짐, (d) 힌지 모드 변화·`hyprctl reload` 후에도 유지, (e) Q1·Q2 관찰.
4. **실제 장치 읽기 시험(배포 없이)**: 스크립트를 노트북에 설치하지 않고 `ssh msi-summit-me "python3 -I - status" < extkbd.py` 로 실행해 판정을 확인한다(읽기 전용).
5. 위 1~4 중 노트북을 직접 만져야 하는 것(키보드 전원 조작, 입력 확인)은 사용자가 한다.

## 6. 구현 결과 (2026-10-27)
**만든 것(저장소 변경, 아직 노트북에 배포되지 않음)**
- `mods/_tools/desktop/external-keyboard/extkbd.py`, `mods/_tools/desktop/external-keyboard/tests/test_extkbd.py`, `mods/_tools/run-tests.sh` 의 목록에 `extkbd` 추가.
- `mods/gui/base/core.bind.hwctl.nix`: `extkbd` CLI 정의, `hypr-input-policy` 수정(flock, `ext` 판정, 노트북 모드에서 외부 키보드가 있으면 키보드 끔, 알림·저널), `extkbd-watch` 사용자 서비스(노트북이고 `internalKeyboardName` 이 있을 때만), 패키지 목록에 `extkbd` 추가.

**확인한 것**
- 자동 시험 32개 통과(판정 규칙, 블루투스 미확인 시 "없음", 제거된 노드 무시, 이벤트 필터, 감시 데몬 프로세스 전체: 시작 시 1회, 디바운스로 3개 이벤트가 1회, BlueZ `Connected` 변화에 실행, 배터리 변화는 무시, 자식 종료 시 데몬 종료).
- 실제 노트북 장치로 `extkbd status`/`present`: 내장 `AT Translated Set 2 keyboard` 는 제외, 연결된 `AULA-F87Pro 5.0 Keyboard`(블루투스, `Connected`)는 "외부"로 판정, `present` 종료 코드 0 (읽기 전용 실행; 이 시험으로 F4 의 오류를 발견·수정).
- Nix: `donghans@msi-summit-me` 의 `activationPackage` 평가 성공, `extkbd-watch` 가 msi 에만 생김, 생성된 정책 스크립트 `bash -n` 통과.

**아직 확인하지 못한 것 (배포 후 실기에서 확인)**
- 정책이 실제로 Hyprland 에서 내장 키보드를 끄고 켜는지, 서비스가 로그인 시 정상 기동하는지.
- Q1(블루투스 키보드가 잠들거나 꺼질 때의 동작), Q2, Q5(BlueZ 신호 수신), Q3·Q4(수신기·키보드 기능이 있는 마우스).
- `policy.lock` 의 flock 이 실제 동시 실행에서 의도대로 동작하는지(코드만 읽음, 시험하지 않음).

