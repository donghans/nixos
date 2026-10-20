"""dispctl — displayctl 의 본체 패키지: Hyprland 화면 관리 (확장/미러/내장만/외부만, 해상도·주사율·배율·상대 위치, 프리젠테이션)

원리
- 모니터 정보는 `hyprctl monitors all -j`, 변경은 `hyprctl eval 'hl.monitor({...})'` 로 한다.
- 모든 전환을 `hyprctl reload` 없이 "명시 규칙"으로 한다. 두 필드를 항상 같이 줘야 상태가 확실히 바뀐다:
  `disabled = false`(없으면 꺼졌던 모니터가 안 켜짐), `mirror = ""`(없으면 미러가 안 풀림).
- 사용자가 정한 구성은 상태 파일(~/.local/state/displayctl/state.json)에 두고, 시작·설정 reload·모니터 연결/해제 때
  `displayctl restore` 로 다시 적용한다 (Hyprland 는 reload 때 런타임 설정을 지움).
- 모니터가 알려 주는 모드(EDID) 외의 해상도/주사율도 시도할 수 있다. 적용 뒤 실제 모드를 읽어 요청과 다르면 알려 준다
  (예: 내장 패널은 48Hz 는 되지만 45/30Hz 는 60Hz 로 돌아감).

되돌리기 타이머: 해상도/주사율처럼 화면이 안 나올 수 있는 변경은 적용 직전에 "이전 구성 + 만료 시각"을 pending.json 에 기록하고
systemd 사용자 타이머(displayctl-revert)가 시간이 지나면 `displayctl revert-pending` 을 실행해 되돌린다. TUI 나 터미널이 죽어도
(화면이 안 나와서 확인을 못 해도) 별도 프로세스가 되돌린다. 확인(`displayctl confirm`)하면 기록을 지우고 타이머를 취소한다.

(Nix 가 @hyprctl@, @notify_send@ 자리표시자를 실제 경로로 치환한다 — mods/gui/base/display-manager.nix)

모듈 구성(위에서 아래로만 import 한다 — 순환 없음):
  config       상수/환경변수/선택지/내장 프리셋 (Nix 자리표시자 치환 대상)
  hypr         hyprctl 호출, 모니터 읽기(Mon), 모드 문자열/묶음
  state        잠금, 상태 파일
  layout       구성 계산(순수 함수), Lua 규칙 문자열
  apply        규칙 적용(겹침 방지 순서), 검증, 창 이동, 회전/터치 동기화
  transaction  되돌리기(pending.json, systemd 타이머, Transaction)
  ops          동작(layout/set/rotate/preset/back), go, restore
  cli          명령줄(argparse, cmd_*), main
진입점은 한 단계 위의 displayctl.py(얇은 파일)이고, 이전 단일 파일의 이름을 쓰는 displayui 와 시험은 `import displayctl as dc` 로 그대로 쓴다.
"""
from . import config, hypr, state, layout, apply, transaction, ops, cli   # noqa: F401  (아래 순서가 의존 순서)

# 이전 단일 파일(displayctl.py)의 이름을 그대로 쓰는 코드를 위해 모든 이름을 패키지 수준으로 올린다(밑줄 이름 포함)
for _m in (config, hypr, state, layout, apply, transaction, ops, cli):
    for _k, _v in vars(_m).items():
        if not _k.startswith("__") and _k not in globals():
            globals()[_k] = _v
del _m, _k, _v
