#!/usr/bin/env bash
# Lightsail $5 headscale 프론트엔드 + DERP 릴레이 + tailscale exit node
# OS: Amazon Linux 2023 (NixOS 미사용)
#
# 역할:
#   - Caddy (TLS 종료): e2.772610158.xyz:443
#     ├── /derp* → localhost:3340 (derper HTTP 모드)
#     └── * → EC2 private IP:8080 (headscale 컨트롤 플레인, VPC 백본)
#   - derper: HTTP 모드 (--dev), STUN UDP:3478
#   - tailscale exit node: headscale에 등록
#
# 사전 조건:
#   - Lightsail ↔ EC2 VPC 피어링 활성화 (Lightsail 콘솔 → 계정 → 고급)
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

# ── 2. IP 포워딩 (exit node 필수) ─────────────────────────────────────────────
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

# ── 4. derper 바이너리 설치 ───────────────────────────────────────────────────
if [ ! -f /usr/local/bin/derper ]; then
    echo "==> derper 바이너리 설치 중..."
    TS_VERSION=$(tailscale version | awk 'NR==1{print $1}')
    ARCH=$(uname -m | sed 's/x86_64/amd64/;s/aarch64/arm64/')
    TGZ="tailscale_${TS_VERSION}_linux_${ARCH}.tgz"
    TMPDIR=$(mktemp -d)

    curl -fsSL \
        "https://github.com/tailscale/tailscale/releases/download/v${TS_VERSION}/${TGZ}" \
        -o "$TMPDIR/$TGZ"
    tar -xzf "$TMPDIR/$TGZ" -C "$TMPDIR"

    DERPER_BIN="$TMPDIR/tailscale_${TS_VERSION}_linux_${ARCH}/derper"
    if [ ! -f "$DERPER_BIN" ]; then
        echo "ERROR: derper가 tailscale ${TS_VERSION} 릴리즈에 포함되지 않음" >&2
        echo "대안: ec2-nixos-headscale.nix의 derp.server.enabled = true 로 되돌리고" >&2
        echo "      headscale 내장 DERP를 사용하세요 (EC2 데이터 전송비 발생)." >&2
        rm -rf "$TMPDIR"
        exit 1
    fi

    install -m 755 "$DERPER_BIN" /usr/local/bin/derper
    rm -rf "$TMPDIR"
fi

# ── 5. derper 실행 사용자 생성 ────────────────────────────────────────────────
id derper &>/dev/null || useradd -r -s /bin/false -d /var/lib/derper derper
mkdir -p /var/lib/derper
chown derper:derper /var/lib/derper

# ── 6. derper systemd 서비스 (HTTP 모드, --dev = Caddy 뒤에서 동작) ──────────
# --dev: localhost:3340 HTTP 서버 (TLS 없음, 리버스 프록시 전용)
# STUN은 --dev 와 무관하게 UDP 3478에서 독립 동작
cat > /etc/systemd/system/derper.service << EOF
[Unit]
Description=Tailscale DERP relay server
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/derper \
  --hostname=${HEADSCALE_DOMAIN} \
  --dev \
  --stun \
  --stun-port=3478 \
  --verify-clients=false
StateDirectory=derper
WorkingDirectory=/var/lib/derper
User=derper
Group=derper
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF

# ── 7. Caddy 설치 ─────────────────────────────────────────────────────────────
if ! command -v caddy &>/dev/null; then
    echo "==> Caddy 설치 중..."
    dnf install -y 'dnf-command(copr)'
    dnf copr enable -y @caddy/caddy
    dnf install -y caddy
fi

# ── 8. Caddy 설정 (TLS 종료 + 라우팅) ────────────────────────────────────────
cat > /etc/caddy/Caddyfile << EOF
${HEADSCALE_DOMAIN} {
    @derp path /derp /derp/*
    reverse_proxy @derp http://localhost:3340

    reverse_proxy * http://${EC2_PRIVATE_IP}:8080 {
        header_up Host {host}
        header_up X-Forwarded-For {remote_host}
        header_up X-Forwarded-Proto {scheme}
    }
}
EOF

systemctl daemon-reload
systemctl enable --now derper
systemctl enable --now caddy

# ── 완료 ─────────────────────────────────────────────────────────────────────
echo ""
echo "==> 설정 완료"
echo "    tailscale 상태: $(tailscale status 2>/dev/null | head -1)"
echo "    derper:         $(systemctl is-active derper)"
echo "    caddy:          $(systemctl is-active caddy)"
echo ""
echo "headscale에서 exit node 승인 필요:"
echo "  sudo headscale routes list"
echo "  sudo headscale routes enable -r <ROUTE_ID>"
