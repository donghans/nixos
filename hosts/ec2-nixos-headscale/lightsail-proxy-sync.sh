#!/usr/bin/env bash
# Lightsail headscale-proxy 라이프사이클 동기화
# 환경변수로 설정값을 받음 (lightsail-proxy.nix의 systemd Environment 참고)
set -euo pipefail

AWS="aws --region $REGION"
SSH_OPTS="-i $LIGHTSAIL_SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o BatchMode=yes -o ConnectTimeout=15 -o LogLevel=ERROR"

log() { echo "lightsail-proxy-sync: $*"; }
err() { echo "lightsail-proxy-sync: $*" >&2; exit 1; }

ETH0_IP=$(ip -4 addr show eth0 | grep -oP '(?<=inet )[0-9.]+' | head -1)
[ -z "$ETH0_IP" ] && err "eth0 IP 읽기 실패"

# ── 인스턴스 존재 확인 ─────────────────────────────────────────────────────────
if $AWS lightsail get-instance --instance-name "$INSTANCE_NAME" &>/dev/null; then
  LS_IP=$($AWS lightsail get-static-ip --static-ip-name "$STATIC_IP_NAME" \
    --query 'staticIp.ipAddress' --output text 2>/dev/null || true)
  [ -z "$LS_IP" ] && err "Static IP 조회 실패"

  # ── 초기화 완료 여부 확인 (Caddy 실행 중 = 초기화 완료) ──────────────────────
  if ! ssh $SSH_OPTS "${LIGHTSAIL_USER}@${LS_IP}" \
      "systemctl is-active --quiet caddy" 2>/dev/null; then
    log "인스턴스 존재하나 초기화 미완료 → 초기화 실행"
    HEADSCALE_DOMAIN="${HEADSCALE_URL#https://}"
    ssh $SSH_OPTS "${LIGHTSAIL_USER}@${LS_IP}" bash -s -- "$ETH0_IP" "$HEADSCALE_DOMAIN" << 'ENDINIT'
EC2_IP="$1"
HEADSCALE_DOMAIN="$2"
set -euo pipefail
if ! command -v tailscale &>/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
sudo systemctl enable --now tailscaled
sudo tee /etc/sysctl.d/99-forwarding.conf << 'EOF'
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
EOF
sudo tee /etc/sysctl.d/99-disable-ipv6.conf << 'EOF'
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
EOF
sudo sysctl -p /etc/sysctl.d/99-forwarding.conf
sudo sysctl -p /etc/sysctl.d/99-disable-ipv6.conf
if ! command -v caddy &>/dev/null; then
  CADDY_VER=$(curl -sL https://api.github.com/repos/caddyserver/caddy/releases/latest \
    | grep '"tag_name"' | cut -d'"' -f4 | cut -c2-)
  curl -sL "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VER}/caddy_${CADDY_VER}_linux_amd64.tar.gz" \
    | sudo tar -xz -C /usr/local/bin caddy
  sudo chmod +x /usr/local/bin/caddy
  sudo useradd -r -s /sbin/nologin caddy 2>/dev/null || true
  sudo mkdir -p /etc/caddy
  sudo chown caddy:caddy /etc/caddy
  sudo tee /etc/systemd/system/caddy.service > /dev/null << 'CADDYUNIT'
[Unit]
Description=Caddy
After=network.target

[Service]
User=caddy
Group=caddy
ExecStart=/usr/local/bin/caddy run --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile
TimeoutStopSec=5s
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
CADDYUNIT
  sudo systemctl daemon-reload
fi
sudo tee /etc/caddy/Caddyfile > /dev/null << CADDYEOF
${HEADSCALE_DOMAIN} {
    reverse_proxy * http://${EC2_IP}:8080 {
        header_up Host {host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }
}
CADDYEOF
sudo systemctl daemon-reload
sudo systemctl enable --now caddy
if ! sudo iptables -t nat -C PREROUTING -p udp --dport 3478 \
    -j DNAT --to-destination "${EC2_IP}:3478" 2>/dev/null; then
  sudo iptables -t nat -A PREROUTING -p udp --dport 3478 \
    -j DNAT --to-destination "${EC2_IP}:3478"
fi
if ! sudo iptables -t nat -C POSTROUTING -p udp -d "${EC2_IP}" \
    --dport 3478 -j MASQUERADE 2>/dev/null; then
  sudo iptables -t nat -A POSTROUTING -p udp -d "${EC2_IP}" \
    --dport 3478 -j MASQUERADE
fi
sudo dnf install -y iptables-services 2>/dev/null || true
sudo iptables-save | sudo tee /etc/sysconfig/iptables > /dev/null
sudo systemctl enable iptables
ENDINIT
    log "초기화 완료"

    # state 주입 + tailscale 등록
    cat "$TS_STATE" \
      | ssh $SSH_OPTS "${LIGHTSAIL_USER}@${LS_IP}" \
          "sudo mkdir -p /var/lib/tailscale && \
           sudo tee /var/lib/tailscale/tailscaled.state > /dev/null && \
           sudo chmod 600 /var/lib/tailscale/tailscaled.state"
    REGISTER_URL=$(ssh $SSH_OPTS "${LIGHTSAIL_USER}@${LS_IP}" \
      "sudo tailscale up \
        --login-server='$HEADSCALE_URL' \
        --hostname='$INSTANCE_NAME' \
        --advertise-exit-node \
        --accept-routes 2>&1" | grep -oP 'https://\S+' | head -1 || true)
    if [ -n "$REGISTER_URL" ]; then
      TOKEN=$(echo "$REGISTER_URL" | grep -oP '(?<=/register/)\S+')
      [ -n "$TOKEN" ] && headscale nodes register --user system --key "$TOKEN"
      log "tailscale node 등록 완료"
    else
      log "tailscale 연결 완료 (기존 노드 재사용)"
    fi
  else
    log "인스턴스 존재 → 갱신 모드"
  fi

  # ── Caddy 갱신 ───────────────────────────────────────────────────────────────
  CURRENT_IP=$(ssh $SSH_OPTS "${LIGHTSAIL_USER}@${LS_IP}" \
    "grep -oP 'http://\K[0-9.]+(?=:8080)' /etc/caddy/Caddyfile 2>/dev/null | head -1" || true)
  if [ "$CURRENT_IP" = "$ETH0_IP" ]; then
    log "Caddy IP 동일 ($ETH0_IP), 갱신 불필요"
  else
    log "Caddy 갱신: ${CURRENT_IP:-'(없음)'} → $ETH0_IP"
    ssh $SSH_OPTS "${LIGHTSAIL_USER}@${LS_IP}" bash -s -- "$ETH0_IP" << 'ENDSSH'
NEW_IP="$1"
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak
sudo sed -i "s|http://[0-9.]*:8080|http://${NEW_IP}:8080|g" /etc/caddy/Caddyfile
sudo systemctl reload caddy 2>/dev/null || sudo systemctl restart caddy
sudo systemctl is-active --quiet caddy
ENDSSH
    log "Caddy 갱신 완료"
  fi

  # ── iptables DNAT 갱신 ───────────────────────────────────────────────────────
  CURRENT_DNAT=$(ssh $SSH_OPTS "${LIGHTSAIL_USER}@${LS_IP}" \
    "sudo iptables -t nat -L PREROUTING -n 2>/dev/null | awk '/dpt:3478.*DNAT/{print \$NF}' | grep -oP 'to:\K[0-9.]+' | head -1" || true)
  if [ "$CURRENT_DNAT" = "$ETH0_IP" ]; then
    log "DNAT 규칙 동일 ($ETH0_IP), 갱신 불필요"
  else
    log "DNAT 갱신: ${CURRENT_DNAT:-'(없음)'} → $ETH0_IP"
    ssh $SSH_OPTS "${LIGHTSAIL_USER}@${LS_IP}" bash -s -- "$CURRENT_DNAT" "$ETH0_IP" << 'ENDSSH'
OLD_IP="$1"
NEW_IP="$2"
[ -n "$OLD_IP" ] && {
  sudo iptables -t nat -D PREROUTING -p udp --dport 3478 -j DNAT --to-destination "${OLD_IP}:3478" 2>/dev/null || true
  sudo iptables -t nat -D POSTROUTING -p udp -d "$OLD_IP" --dport 3478 -j MASQUERADE 2>/dev/null || true
}
sudo iptables -t nat -A PREROUTING -p udp --dport 3478 -j DNAT --to-destination "${NEW_IP}:3478"
sudo iptables -t nat -A POSTROUTING -p udp -d "$NEW_IP" --dport 3478 -j MASQUERADE
sudo iptables-save | sudo tee /etc/sysconfig/iptables > /dev/null
ENDSSH
    log "DNAT 갱신 완료"
  fi

else
  log "인스턴스 없음 → 생성 모드"

  # ── state 파일 확인 ───────────────────────────────────────────────────────────
  [ -f "$TS_STATE" ] \
    || err "tailscale state 파일 없음 ($TS_STATE) — lightsail-ts-keygen.sh를 먼저 실행하세요"

  # ── 키페어 import (idempotent: delete → reimport) ─────────────────────────
  $AWS lightsail delete-key-pair --key-pair-name "$KEY_PAIR_NAME" &>/dev/null || true
  $AWS lightsail import-key-pair \
    --key-pair-name "$KEY_PAIR_NAME" \
    --public-key-base64 "$(cat "$LIGHTSAIL_PUB_KEY")"
  log "키페어 import 완료"

  # ── Static IP 확보 ───────────────────────────────────────────────────────────
  STATIC_IP_INFO=$($AWS lightsail get-static-ip --static-ip-name "$STATIC_IP_NAME" \
    --query 'staticIp' --output json 2>/dev/null || echo "null")
  if [ "$STATIC_IP_INFO" = "null" ]; then
    $AWS lightsail allocate-static-ip --static-ip-name "$STATIC_IP_NAME"
    log "Static IP 할당 완료"
  else
    ATTACHED_TO=$(echo "$STATIC_IP_INFO" | jq -r '.attachedTo // empty')
    [ -n "$ATTACHED_TO" ] && err "Static IP '$STATIC_IP_NAME'이 '$ATTACHED_TO'에 이미 연결됨 — 수동 해제 필요"
    log "Static IP 재사용"
  fi
  LS_IP=$($AWS lightsail get-static-ip --static-ip-name "$STATIC_IP_NAME" \
    --query 'staticIp.ipAddress' --output text)

  # ── VPC 피어링 ───────────────────────────────────────────────────────────────
  PEERED=$($AWS lightsail is-vpc-peered \
    --query 'isPeered' --output text 2>/dev/null || echo "unknown")
  if [ "$PEERED" = "True" ]; then
    log "VPC 피어링 이미 활성화"
  elif $AWS lightsail peer-vpc 2>/dev/null; then
    log "VPC 피어링 활성화 완료"
  else
    log "VPC 피어링 확인/활성화 실패 — Lightsail 콘솔에서 수동으로 확인하세요:"
    log "  Lightsail 콘솔 → 계정 → 고급 → VPC 피어링"
  fi

  # ── 인스턴스 생성 (UserData 없음 — SSH로 모든 초기화 처리) ───────────────────
  $AWS lightsail create-instances \
    --instance-names "$INSTANCE_NAME" \
    --availability-zone "${REGION}a" \
    --blueprint-id "$BLUEPRINT" \
    --bundle-id "$BUNDLE" \
    --key-pair-name "$KEY_PAIR_NAME"
  log "인스턴스 생성 요청 완료"

  # ── running 대기 (최대 5분) ───────────────────────────────────────────────────
  for i in $(seq 1 10); do
    STATE=$($AWS lightsail get-instance-state \
      --instance-name "$INSTANCE_NAME" \
      --query 'state.name' --output text 2>/dev/null || echo "unknown")
    [ "$STATE" = "running" ] && break
    log "대기 중... ($STATE, $i/10)"
    sleep 30
  done
  STATE=$($AWS lightsail get-instance-state \
    --instance-name "$INSTANCE_NAME" \
    --query 'state.name' --output text 2>/dev/null || echo "unknown")
  [ "$STATE" != "running" ] && err "5분 내 running 미진입"

  # ── Static IP 연결 ───────────────────────────────────────────────────────────
  $AWS lightsail attach-static-ip \
    --static-ip-name "$STATIC_IP_NAME" \
    --instance-name "$INSTANCE_NAME"
  log "Static IP 연결 완료 ($LS_IP)"

  # ── SSH 접속 대기 (sshd 시작까지) ────────────────────────────────────────────
  log "SSH 접속 대기 중 (최대 3분)..."
  SSH_OK=false
  for i in $(seq 1 6); do
    ssh $SSH_OPTS "${LIGHTSAIL_USER}@${LS_IP}" true 2>/dev/null && SSH_OK=true && break
    log "SSH 대기 중... ($i/6)"
    sleep 30
  done
  [ "$SSH_OK" = false ] && err "SSH 접속 실패 — Lightsail 상태 수동 확인 필요"

  # ── SSH로 전체 초기화 ─────────────────────────────────────────────────────────
  HEADSCALE_DOMAIN="${HEADSCALE_URL#https://}"
  log "Lightsail 초기화 중 (tailscale + Caddy + iptables)..."
  ssh $SSH_OPTS "${LIGHTSAIL_USER}@${LS_IP}" bash -s -- "$ETH0_IP" "$HEADSCALE_DOMAIN" << 'ENDINIT'
EC2_IP="$1"
HEADSCALE_DOMAIN="$2"
set -euo pipefail

# tailscale 설치 + tailscaled 시작
if ! command -v tailscale &>/dev/null; then
  curl -fsSL https://tailscale.com/install.sh | sh
fi
sudo systemctl enable --now tailscaled

# IP 포워딩
sudo tee /etc/sysctl.d/99-forwarding.conf << 'EOF'
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
EOF
sudo tee /etc/sysctl.d/99-disable-ipv6.conf << 'EOF'
net.ipv6.conf.all.disable_ipv6 = 1
net.ipv6.conf.default.disable_ipv6 = 1
EOF
sudo sysctl -p /etc/sysctl.d/99-forwarding.conf
sudo sysctl -p /etc/sysctl.d/99-disable-ipv6.conf

# Caddy 설치
if ! command -v caddy &>/dev/null; then
  CADDY_VER=$(curl -sL https://api.github.com/repos/caddyserver/caddy/releases/latest \
    | grep '"tag_name"' | cut -d'"' -f4 | cut -c2-)
  curl -sL "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VER}/caddy_${CADDY_VER}_linux_amd64.tar.gz" \
    | sudo tar -xz -C /usr/local/bin caddy
  sudo chmod +x /usr/local/bin/caddy
  sudo useradd -r -s /sbin/nologin caddy 2>/dev/null || true
  sudo mkdir -p /etc/caddy
  sudo chown caddy:caddy /etc/caddy
  sudo tee /etc/systemd/system/caddy.service > /dev/null << 'CADDYUNIT'
[Unit]
Description=Caddy
After=network.target

[Service]
User=caddy
Group=caddy
ExecStart=/usr/local/bin/caddy run --config /etc/caddy/Caddyfile
ExecReload=/usr/local/bin/caddy reload --config /etc/caddy/Caddyfile
TimeoutStopSec=5s
AmbientCapabilities=CAP_NET_BIND_SERVICE

[Install]
WantedBy=multi-user.target
CADDYUNIT
  sudo systemctl daemon-reload
fi

# Caddy 설정
sudo tee /etc/caddy/Caddyfile > /dev/null << CADDYEOF
${HEADSCALE_DOMAIN} {
    reverse_proxy * http://${EC2_IP}:8080 {
        header_up Host {host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }
}
CADDYEOF
sudo systemctl daemon-reload
sudo systemctl enable --now caddy

# iptables DNAT
if ! sudo iptables -t nat -C PREROUTING -p udp --dport 3478 \
    -j DNAT --to-destination "${EC2_IP}:3478" 2>/dev/null; then
  sudo iptables -t nat -A PREROUTING -p udp --dport 3478 \
    -j DNAT --to-destination "${EC2_IP}:3478"
fi
if ! sudo iptables -t nat -C POSTROUTING -p udp -d "${EC2_IP}" \
    --dport 3478 -j MASQUERADE 2>/dev/null; then
  sudo iptables -t nat -A POSTROUTING -p udp -d "${EC2_IP}" \
    --dport 3478 -j MASQUERADE
fi
sudo dnf install -y iptables-services 2>/dev/null || true
sudo iptables-save | sudo tee /etc/sysconfig/iptables > /dev/null
sudo systemctl enable iptables
ENDINIT
  log "초기화 완료"

  # ── tailscale state 주입 ──────────────────────────────────────────────────────
  log "tailscale state 주입 중..."
  cat "$TS_STATE" \
    | ssh $SSH_OPTS "${LIGHTSAIL_USER}@${LS_IP}" \
        "sudo mkdir -p /var/lib/tailscale && \
         sudo tee /var/lib/tailscale/tailscaled.state > /dev/null && \
         sudo chmod 600 /var/lib/tailscale/tailscaled.state"

  # ── tailscale up → headscale 등록 URL 추출 → nodes register ─────────────────
  REGISTER_URL=$(ssh $SSH_OPTS "${LIGHTSAIL_USER}@${LS_IP}" \
    "sudo tailscale up \
      --login-server='$HEADSCALE_URL' \
      --hostname='$INSTANCE_NAME' \
      --advertise-exit-node \
      --accept-routes 2>&1" | grep -oP 'https://\S+' | head -1 || true)

  if [ -n "$REGISTER_URL" ]; then
    TOKEN=$(echo "$REGISTER_URL" | grep -oP '(?<=/register/)\S+')
    [ -n "$TOKEN" ] && headscale nodes register --user system --key "$TOKEN"
    log "tailscale node 등록 완료"
  else
    log "tailscale 연결 완료 (기존 노드 재사용)"
  fi

  # ── exit node route 승인 ─────────────────────────────────────────────────────
  log "exit node route 승인 대기 중 (최대 3분)..."
  for i in $(seq 1 6); do
    NODE_ID=$(headscale nodes list --output json 2>/dev/null \
      | jq -r '.[] | select(.name == "'"$INSTANCE_NAME"'") | .id' || true)
    if [ -n "$NODE_ID" ]; then
      ROUTE_ID=$(headscale routes list --output json 2>/dev/null \
        | jq -r '.[] | select(.node.id == "'"$NODE_ID"'" and .advertised == true) | .id' || true)
      if [ -n "$ROUTE_ID" ]; then
        headscale routes enable -r "$ROUTE_ID"
        log "exit node route 승인 완료 (route: $ROUTE_ID)"
        break
      fi
    fi
    log "대기 중... ($i/6)"
    sleep 30
  done
fi
