# 배터리 절전으로 밝기를 낮춘 상태(displayctl brightness)면 먼저 원래 밝기로 깨운다.
# 안 그러면 낮춘 밝기 기준으로 조절된 뒤 hypridle 의 복귀(wake)가 원래 밝기로 덮어써서 사용자의 변경이 사라진다.
# 낮춘 상태일 때만 displayctl(파이썬)을 부른다 — 평소 키 입력에 지연을 주지 않으려고 런타임 상태 파일을 쉘에서 먼저 본다.
if grep -qs '"dimmed": [0-9]' "${XDG_RUNTIME_DIR:-/tmp}/displayctl-brightness.json"; then
  command -v displayctl >/dev/null && displayctl brightness wake
fi
# 단계: 10% 이하는 1%씩(어두운 쪽은 눈이 민감), 그 위는 5%의 배수로 맞춰 5%씩. 최소 1%(0 은 백라이트가 꺼져 덮개 닫힘과 구분이 안 됨).
# dispctl/brightness.py 의 step_pct 와 같은 규칙이어야 함(displayui 슬라이더)
cur=$(@brightnessctl@ get); max=$(@brightnessctl@ max)
pct=$(( (cur * 100 + max / 2) / max ))
case $1 in
  up)
    if [ "$pct" -lt 10 ]; then t=$((pct + 1)); else t=$(( (pct / 5 + 1) * 5 )); fi
    [ "$t" -gt 100 ] && t=100
    ;;
  down)
    if [ "$pct" -le 10 ]; then t=$((pct - 1)); else t=$(( ((pct + 4) / 5 - 1) * 5 )); fi
    [ "$t" -lt 1 ] && t=1
    ;;
esac
[ -n "$t" ] && @brightnessctl@ -q set "$t%"

BRT=$(@brightnessctl@ -m | cut -d, -f4 | tr -d '%')
@notify_send@ -h string:x-canonical-private-synchronous:brightness -h int:value:"$BRT" -u low "Brightness" "$BRT%"
