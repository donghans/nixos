#!/bin/bash
# qa-desktop VM 프로비저닝 — VM 안에서 root 로 실행한다(호스트의 qa-desktop-ctl 이 `incus exec` 로 stdin 에 넣는다). **멱등**: 여러 번 돌려도 안전하다.
#
# 입력(환경변수):
#   QA_USER        VM 의 데스크톱 사용자 이름(기본 qa). 이미지의 기본 사용자 `ubuntu`(uid 1000)를 이 이름으로 바꾼다 — uid 1000 이라 /run/user/1000 을 가정한 도구가 그대로 동작한다.
#   QA_PUBKEY      호스트에서 ssh 로 들어올 공개키 한 줄(필수)
#   QA_PLAYWRIGHT  playwright 버전 범위(기본 ~1.63.0 — 모든 프로젝트가 공유. `^` 로 두면 새 마이너가 나올 때마다 달라진다)
#   QA_PROJECTS    프로젝트별 창 배치 규칙 「이름:데스크톱번호」 공백 구분(예: "genple:2"). 이름은 Chromium `--class=<이름>-qa` 와 짝이다.
#   QA_TOOLS_DIR   (선택) 호스트가 미리 넣어 둔 도구 디렉터리(ws.py·snap.py·occupy 대상) — 있으면 ~/qa-tools 로 복사
# 하는 일: 사용자·ssh · GDM 자동 로그인 · 화면 잠금/절전 끔 · Auto Move Windows 확장과 규칙 · Playwright(Chromium) · run.sh · 프로젝트별 .desktop · GDM 재시작.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
QA_USER="${QA_USER:-qa}"
QA_PLAYWRIGHT="${QA_PLAYWRIGHT:-~1.63.0}"
QA_PROJECTS="${QA_PROJECTS:-}"
: "${QA_PUBKEY:?QA_PUBKEY 가 필요하다}"
log() { echo "[provision $(date +%T)] $*"; }
EXT="auto-move-windows@gnome-shell-extensions.gcampax.github.com"

# 0) 네트워크가 잡힐 때까지 기다린 뒤 패키지 목록 갱신
for _ in $(seq 1 60); do getent hosts archive.ubuntu.com >/dev/null 2>&1 && break; sleep 2; done
log "apt update"; apt-get update -qq

# 1) 사용자: 이미지 기본 사용자(ubuntu, uid 1000)를 QA_USER 로 이름 변경(이미 바뀌었으면 건너뜀). 로그인 세션이 붙어 있으면 이름을 못 바꾸므로 GDM 을 먼저 멈춘다.
if ! id "$QA_USER" >/dev/null 2>&1; then
  if id ubuntu >/dev/null 2>&1; then
    log "사용자 ubuntu → $QA_USER (uid $(id -u ubuntu))"
    systemctl stop gdm3 2>/dev/null || true
    loginctl terminate-user ubuntu 2>/dev/null || true
    for _ in $(seq 1 20); do pgrep -u ubuntu >/dev/null 2>&1 || break; sleep 1; done
    pkill -KILL -u ubuntu 2>/dev/null || true
    usermod -l "$QA_USER" -d "/home/$QA_USER" -m ubuntu
    groupmod -n "$QA_USER" ubuntu 2>/dev/null || true
    rm -f /etc/sudoers.d/90-cloud-init-users
    rm -f /var/crash/*.crash /var/crash/*.upload /var/crash/*.uploaded 2>/dev/null || true   # 세션을 강제로 끊어 생긴 gnome-shell 크래시 보고(새 세션에 apport 대화상자가 뜬다)
  else
    useradd -m -s /bin/bash "$QA_USER"
  fi
fi
usermod -p '*' "$QA_USER"   # 비밀번호 로그인은 막고(잠금 표시가 아님) 키 로그인만 허용 — 화면 잠금이 걸리면 GUI 로는 풀 수 없으니 잠금은 아래에서 끈다
echo "$QA_USER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$QA_USER"; chmod 440 "/etc/sudoers.d/90-$QA_USER"
UHOME=$(getent passwd "$QA_USER" | cut -d: -f6); UID_N=$(id -u "$QA_USER")

# 2) 패키지(한 번에)
log "패키지 설치"
apt-get install -y -qq openssh-server sudo curl ca-certificates dconf-cli nodejs npm python3-gi gir1.2-glib-2.0 \
  gstreamer1.0-pipewire gstreamer1.0-plugins-base gstreamer1.0-plugins-good gnome-shell-extension-auto-move-windows >/dev/null

# 3) ssh: 호스트 키만
install -d -m 700 -o "$QA_USER" -g "$QA_USER" "$UHOME/.ssh"
touch "$UHOME/.ssh/authorized_keys"; chmod 600 "$UHOME/.ssh/authorized_keys"; chown "$QA_USER:$QA_USER" "$UHOME/.ssh/authorized_keys"
grep -qxF "$QA_PUBKEY" "$UHOME/.ssh/authorized_keys" || echo "$QA_PUBKEY" >> "$UHOME/.ssh/authorized_keys"
systemctl enable --now ssh >/dev/null 2>&1 || systemctl enable --now sshd >/dev/null 2>&1 || true

# 4) GDM 자동 로그인(부팅 직후 한 번만 적용된다 — 재로그인 뒤에는 `systemctl restart gdm3` 필요)
cat > /etc/gdm3/custom.conf <<EOF
[daemon]
AutomaticLoginEnable=true
AutomaticLogin=$QA_USER
EOF

# 5) 시스템 dconf 기본값: 화면 잠금·절전 끔(계정에 비밀번호가 없어 잠기면 GUI 로 풀 수 없다), 확장 켬, 창 배치 규칙
RULES=""
for p in $QA_PROJECTS; do RULES="${RULES}${RULES:+, }'${p%%:*}-qa.desktop:${p##*:}'"; done
install -d /etc/dconf/profile /etc/dconf/db/local.d
printf 'user-db:user\nsystem-db:local\n' > /etc/dconf/profile/user
cat > /etc/dconf/db/local.d/00-qa-desktop <<EOF
[org/gnome/desktop/screensaver]
lock-enabled=false
idle-activation-enabled=false

[org/gnome/desktop/session]
idle-delay=uint32 0

[org/gnome/settings-daemon/plugins/power]
sleep-inactive-ac-type='nothing'
sleep-inactive-battery-type='nothing'

[org/gnome/shell]
enabled-extensions=['$EXT']

[org/gnome/shell/extensions/auto-move-windows]
application-list=[$RULES]
EOF
dconf update
# 첫 로그인 마법사(gnome-initial-setup)는 건너뛴다
install -d -o "$QA_USER" -g "$QA_USER" "$UHOME/.config"; echo yes > "$UHOME/.config/gnome-initial-setup-done"; chown "$QA_USER:$QA_USER" "$UHOME/.config/gnome-initial-setup-done"

# 5-B) 화면을 어지럽히는 첫 실행/알림을 끈다(스크린샷 판정이 오염되지 않게)
#  - 업그레이드 마법사: 실행 조건이 「gnome-initial-setup-done 이 있고 upgrade-<버전>-done 이 없을 때」라, 위에서 만든 done 파일이 오히려 켠다 → 릴리스마다 파일명이 달라지니 유닛을 마스크한다
systemctl --global mask gnome-initial-setup-upgrade-login.service >/dev/null 2>&1 || true
#  - 업데이트·보고 알림 자동시작, 크래시 보고(apport)
install -d -o "$QA_USER" -g "$QA_USER" "$UHOME/.config/autostart"
for a in update-notifier ubuntu-report-on-upgrade; do
  [ -f "/etc/xdg/autostart/$a.desktop" ] && { printf '[Desktop Entry]\nType=Application\nName=%s\nHidden=true\n' "$a" > "$UHOME/.config/autostart/$a.desktop"; chown "$QA_USER:$QA_USER" "$UHOME/.config/autostart/$a.desktop"; }
done
[ -f /etc/default/apport ] && sed -i 's/^enabled=1/enabled=0/' /etc/default/apport
systemctl disable --now apport.service >/dev/null 2>&1 || true
rm -f /var/crash/*.crash /var/crash/*.upload /var/crash/*.uploaded 2>/dev/null || true

# 6) 프로젝트별 창 배치용 .desktop(StartupWMClass 가 Chromium --class=<이름>-qa 와 짝)
install -d -o "$QA_USER" -g "$QA_USER" "$UHOME/.local" "$UHOME/.local/share" "$UHOME/.local/share/applications"
for p in $QA_PROJECTS; do
  n="${p%%:*}"
  cat > "$UHOME/.local/share/applications/$n-qa.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$n QA Browser
Exec=/bin/true
StartupWMClass=$n-qa
NoDisplay=true
EOF
  chown "$QA_USER:$QA_USER" "$UHOME/.local/share/applications/$n-qa.desktop"
done

# 7) Playwright(공유) + Chromium + run.sh + 디렉터리 규칙
log "Playwright $QA_PLAYWRIGHT"
su - "$QA_USER" -c "mkdir -p ~/qa-playwright ~/qa-shots ~/qa-tools && cd ~/qa-playwright && { [ -f package.json ] || npm init -y >/dev/null; } && npm install 'playwright@$QA_PLAYWRIGHT' --no-audit --no-fund --silent && npx playwright install chromium"
( cd "$UHOME/qa-playwright" && npx playwright install-deps chromium >/dev/null 2>&1 || true )
cat > "$UHOME/qa-playwright/run.sh" <<'EOF'
#!/bin/bash
# GUI 세션 env 를 매번 동적으로 잡아 실행 (재부팅·재로그인마다 Xwayland auth 파일명이 바뀜)
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export WAYLAND_DISPLAY=wayland-0
export DISPLAY=:0
export XAUTHORITY=$(ls /run/user/$(id -u)/.mutter-Xwaylandauth.* 2>/dev/null | head -1)
exec node "$@"
EOF
chmod +x "$UHOME/qa-playwright/run.sh"; chown "$QA_USER:$QA_USER" "$UHOME/qa-playwright/run.sh"
if [ -n "${QA_TOOLS_DIR:-}" ] && [ -d "$QA_TOOLS_DIR" ]; then
  cp -r "$QA_TOOLS_DIR"/. "$UHOME/qa-tools/"; chown -R "$QA_USER:$QA_USER" "$UHOME/qa-tools"
fi
for p in $QA_PROJECTS; do su - "$QA_USER" -c "mkdir -p ~/qa-playwright/flow_${p%%:*} ~/qa-shots/${p%%:*}"; done

# 8) 세션을 새로 시작해 자동 로그인·확장·dconf 를 적용
log "GDM 재시작"
systemctl restart gdm3
log "완료(uid $UID_N, 규칙: ${QA_PROJECTS:-없음})"
