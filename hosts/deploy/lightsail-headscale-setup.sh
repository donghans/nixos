#!/usr/bin/env bash
# Lightsail $5 headscale 프론트엔드 + STUN DNAT + tailscale exit node
# OS: Amazon Linux 2023 (NixOS 미사용)
#
# 역할:
#   - Caddy (TLS 종료): e.772610158.xyz:443 → EC2 private IP:8080 (headscale)
#   - iptables DNAT: UDP 3478 → EC2 private IP:3478 (headscale 내장 STUN)
#   - tailscale exit node: headscale에 등록
#
# 사전 조건:
#   - Lightsail ↔ EC2 VPC 피어링 활성화 (Lightsail 콘솔 → 계정 → 고급)
#   - EC2 보안 그룹: UDP 3478 인바운드 허용 (Lightsail VPC 대역 172.26.0.0/16)
#   - headscale에서 preauth key 생성:
#       ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@<EC2_IP> \
#         "sudo headscale preauthkeys create -u system --expiration 24h"
#
# 사용법 (서버에서 root로 실행):
#   sudo bash lightsail-headscale-setup.sh <PREAUTH_KEY> <EC2_PRIVATE_IP>
set -euo pipefail

HEADSCALE_URL="https://e.772610158.xyz"
HEADSCALE_DOMAIN="e.772610158.xyz"
PREAUTH_KEY="${1:-}"
EC2_PRIVATE_IP="${2:-}"

if [ -z "$PREAUTH_KEY" ] || [ -z "$EC2_PRIVATE_IP" ]; then
    echo "Usage: $0 <preauth-key> <ec2-private-ip>" >&2
    exit 1
fi

# ── 1. tailscale 설치 ─────────────────────────────────────────────────────────
if ! command -v tailscale &>/dev/null; then
    echo "==> tailscale 설치 중..."
    curl -fsSL https://tailscale.com/install.sh | sh
fi

# ── 2. IP 포워딩 (exit node + DNAT 필수) ──────────────────────────────────────
echo "==> IP 포워딩 설정..."
cat > /etc/sysctl.d/99-forwarding.conf << 'EOF'
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
EOF
sysctl -p /etc/sysctl.d/99-forwarding.conf

# ── 3. tailscale 시작 + headscale 등록 ───────────────────────────────────────
echo "==> tailscale 시작 및 headscale 등록..."
systemctl enable --now tailscaled
tailscale up \
    --login-server="$HEADSCALE_URL" \
    --authkey="$PREAUTH_KEY" \
    --advertise-exit-node \
    --hostname="lightsail-headscale" \
    --accept-routes

# ── 4. Caddy 설치 ─────────────────────────────────────────────────────────────
if ! command -v caddy &>/dev/null; then
    echo "==> Caddy 설치 중..."
    dnf install -y 'dnf-command(copr)'
    dnf copr enable -y @caddy/caddy
    dnf install -y caddy
fi

# ── 5. Caddy 설정 (TLS 종료 + headscale 프록시) ───────────────────────────────
# DERP WebSocket(/derp)도 headscale이 8080에서 처리하므로 별도 라우팅 불필요
cat > /etc/caddy/Caddyfile << EOF
${HEADSCALE_DOMAIN} {
    reverse_proxy * http://${EC2_PRIVATE_IP}:8080 {
        header_up Host {host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }
}
EOF

systemctl daemon-reload
systemctl enable --now caddy

# ── 6. iptables DNAT: UDP 3478 → EC2 headscale STUN ──────────────────────────
# headscale 내장 STUN은 UDP이므로 Caddy(TCP)로 프록시 불가.
# Lightsail 공인 IP로 들어오는 UDP 3478을 EC2 사설 IP로 포워딩.
echo "==> iptables DNAT 설정..."

if ! iptables -t nat -C PREROUTING -p udp --dport 3478 \
    -j DNAT --to-destination "${EC2_PRIVATE_IP}:3478" 2>/dev/null; then
    iptables -t nat -A PREROUTING -p udp --dport 3478 \
        -j DNAT --to-destination "${EC2_PRIVATE_IP}:3478"
fi
if ! iptables -t nat -C POSTROUTING -p udp -d "${EC2_PRIVATE_IP}" \
    --dport 3478 -j MASQUERADE 2>/dev/null; then
    iptables -t nat -A POSTROUTING -p udp -d "${EC2_PRIVATE_IP}" \
        --dport 3478 -j MASQUERADE
fi

dnf install -y iptables-services 2>/dev/null || true
iptables-save > /etc/sysconfig/iptables
systemctl enable iptables

# ── 완료 ─────────────────────────────────────────────────────────────────────
echo ""
echo "==> 설정 완료"
echo "    tailscale 상태: $(tailscale status 2>/dev/null | head -1)"
echo "    caddy:          $(systemctl is-active caddy)"
echo "    iptables DNAT:  $(iptables -t nat -L PREROUTING -n | grep 3478 | head -1)"
echo ""
echo "headscale에서 exit node 승인 필요:"
echo "  sudo headscale nodes list-routes"
echo "  sudo headscale routes enable -r <ROUTE_ID>"
