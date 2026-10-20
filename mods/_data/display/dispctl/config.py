"""상수와 환경변수(경로, 외부 명령, 화면 모드 선택지, 내장 프리셋). Nix 가 @hyprctl@/@notify_send@ 자리표시자를 이 파일에서 치환한다."""
from __future__ import annotations

import os

HYPRCTL = os.environ.get("DISPLAYCTL_HYPRCTL", "@hyprctl@")
STATE_DIR = os.environ.get("DISPLAYCTL_STATE") or os.path.join(
    os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "displayctl"
)
CONF_DIR = os.environ.get("DISPLAYCTL_CONF") or os.path.join(
    os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "displayctl"
)
STATE_FILE = os.path.join(STATE_DIR, "state.json")
PRESET_FILE = os.path.join(CONF_DIR, "presets.json")
LOCK_FILE = os.path.join(STATE_DIR, "lock")
PENDING_FILE = os.path.join(STATE_DIR, "pending.json")  # 확인 대기 중인 변경(이전 구성 + 만료 시각)
TIMER_UNIT = "displayctl-revert"
SYSTEMD_RUN = os.environ.get("DISPLAYCTL_SYSTEMD_RUN", "systemd-run")
SYSTEMCTL = os.environ.get("DISPLAYCTL_SYSTEMCTL", "systemctl")
POSTURE = os.environ.get("DISPLAYCTL_POSTURE", "posture")
NOTIFY = os.environ.get("DISPLAYCTL_NOTIFY", "@notify_send@")  # 비어 있으면 알림 생략
SETTLE = float(os.environ.get("DISPLAYCTL_SETTLE", "0.8"))  # 적용 뒤 실제 모드를 읽기 시작하기까지 기다리는 시간(초)
VERIFY_TIMEOUT = float(os.environ.get("DISPLAYCTL_VERIFY_TIMEOUT", "4"))  # 검증이 통과할 때까지 기다리는 최대 시간(초)

# 모니터가 알려 주지 않아도 시도해 볼 후보 (적용 뒤 실제 모드로 검증)
COMMON_RES = [
    "3840x2160", "2560x1600", "2560x1440", "1920x1200", "1920x1080",
    "1680x1050", "1600x900", "1440x900", "1366x768", "1280x800", "1280x720",
]
COMMON_HZ = [165, 144, 120, 100, 75, 60, 59.94, 50, 48, 45, 30, 24]
SCALES = [1, 1.25, 1.5, 1.6, 1.75, 2, 2.5, 3]
RELS = {"above": "위", "below": "아래", "left": "왼쪽", "right": "오른쪽"}
ALIGNS = {"start": "시작(위/왼쪽) 맞춤", "center": "가운데 맞춤", "end": "끝(아래/오른쪽) 맞춤"}

# 확장 배치(외부 모니터를 내장 화면 기준 어디에 둘지). 모두 가운데 정렬. stack = 기본(외부 위, 내장 아래)
ARRANGES = {
    "stack": "위아래: 외부 위 / 내장 아래",
    "left": "좌우: 외부 왼쪽 / 내장 오른쪽",
    "right": "좌우: 외부 오른쪽 / 내장 왼쪽",
}

# PC(내장 패널 없음): 첫 모니터가 메인, 나머지가 보조. 화면을 끄는 선택지(메인만/보조만)는 두지 않는다(모니터별로 켜고 끌 수는 있음).
ARRANGES_PC = {
    "stack": "위아래: 보조 위 / 메인 아래",
    "left": "좌우: 보조 왼쪽 / 메인 오른쪽",
    "right": "좌우: 보조 오른쪽 / 메인 왼쪽",
}

LAYOUTS_PC = {
    "extend": "확장 (메인 + 보조)",
    "mirror": "미러 (보조에 메인을 복제)",
}

LAYOUTS = {
    "extend": "확장 (내장 + 외부)",
    "mirror": "미러",
    "internal": "내장 화면만",
    "external": "외부 화면만",
}

# 임시 프리셋: 적용 전 구성을 기억해 두었다가 `displayctl back` 으로 돌아갈 수 있다.
# "@external"/"@internal" 은 첫 번째 외부/내장 모니터를 뜻한다.
BUILTIN_PRESETS = {
    "presentation-1080p": {"label": "프리젠테이션 1920x1080 (미러)", "layout": "mirror", "modes": {"@external": "1920x1080@60"}},
    "presentation-1200p": {"label": "프리젠테이션 1920x1200 (미러)", "layout": "mirror", "modes": {"@external": "1920x1200@60"}},
    "presentation-900p": {"label": "프리젠테이션 1600x900 (미러)", "layout": "mirror", "modes": {"@external": "1600x900@60"}},
    "presentation-720p": {"label": "프리젠테이션 1280x720 (미러)", "layout": "mirror", "modes": {"@external": "1280x720@60"}},
    "laptop-1200p": {"label": "내장만 1920x1200", "layout": "internal", "modes": {"@internal": "1920x1200@60"}},
    "laptop-native": {"label": "내장만 2560x1600 60Hz", "layout": "internal", "modes": {"@internal": "2560x1600@60"}},
}
