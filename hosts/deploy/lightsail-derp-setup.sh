#!/usr/bin/env bash
# Lightsail $5 DERP 릴레이 + tailscale exit node 초기 설정
# OS: Amazon Linux 2023 (기본 Lightsail 이미지)
# RAM: 512MB로 충분 (tailscaled ~50MB + derper ~20MB)
#
# 실행 전 headscale에서 preauth key 생성:
#   ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@<EC2_IP> \
#     "sudo headscale preauthkeys create -u system --expiration 24h"
#
# 사용법 (서버에서 root로 실행):
#   sudo bash lightsail-derp-setup.sh <PREAUTH_KEY>
set -euo pipefail

HEADSCALE_URL="https://e2.772610158.xyz"
DERP_DOMAIN="d.r.772610158.xyz"
PREAUTH_KEY="${1:-}"

if [ -z "$PREAUTH_KEY" ]; then
    echo "Usage: $0 <preauth-key>" >&2
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
    --hostname="derp-relay" \
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
    echo "==> derper $(derper --version 2>/dev/null || echo '설치 완료')"
fi

# ── 5. derper 실행 사용자 생성 ────────────────────────────────────────────────
id derper &>/dev/null || useradd -r -s /bin/false -d /var/lib/derper derper

# ── 6. derper systemd 서비스 등록 ────────────────────────────────────────────
cat > /etc/systemd/system/derper.service << EOF
[Unit]
Description=Tailscale DERP relay server
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/local/bin/derper \\
  --hostname=${DERP_DOMAIN} \\
  --certmode=letsencrypt \\
  --certdir=/var/lib/derper \\
  --addr=:443 \\
  --http-port=80 \\
  --stun \\
  --stun-port=3478 \\
  --verify-clients=false
StateDirectory=derper
User=derper
Group=derper
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
Restart=on-failure
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now derper

# ── 완료 ─────────────────────────────────────────────────────────────────────
echo ""
echo "==> 설정 완료"
echo "    tailscale 상태: $(tailscale status 2>/dev/null | head -1)"
echo "    derper:         $(systemctl is-active derper)"
echo ""
echo "headscale에서 exit node 승인 필요:"
echo "  sudo headscale routes list"
echo "  sudo headscale routes enable -r <ROUTE_ID>"
