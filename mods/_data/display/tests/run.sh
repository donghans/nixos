#!/bin/sh
# 사용: tests/run.sh   (코어 + TUI 시험. 실제 Hyprland 를 건드리지 않음)
D=$(cd "$(dirname "$0")" && pwd)
T=$(mktemp -d)
export FAKE_STATE=$T/fake.json DISPLAYCTL_HYPRCTL=$D/fake_hyprctl.py DISPLAYCTL_STATE=$T/state DISPLAYCTL_CONF=$T/conf DISPLAYCTL_SETTLE=0 DISPLAYCTL_VERIFY_TIMEOUT=0 DISPLAYUI_CONFIRM=3
export DISPLAYCTL_SYSTEMD_RUN=$D/fake_systemd_run.py DISPLAYCTL_SYSTEMCTL=$D/fake_systemctl.py FAKE_UNITS=$T/units DISPLAYCTL_NOTIFY=
export PYTHONDONTWRITEBYTECODE=1 TESTS_TMP=$T
PY=${PYTHON:-python3}
rc=0
$PY -I "$D/test_core.py" || rc=1
$PY "$D/test_ui.py" || rc=1   # textual 이 필요: PYTHON=<textual 이 있는 python> tests/run.sh
rm -rf "$T"
exit $rc
