#!/usr/bin/env bash
# Intermediate CA 교체 스크립트
#
# 실행 위치: root CA 개인키가 있는 로컬 머신
# 사전 조건 (로컬): step CLI, aws CLI, python3, ssh, scp
# 사전 조건 (AWS): 로컬 AWS 자격증명에 아래 권한 필요
#   rolesanywhere:UpdateTrustAnchor
#
# 사용법:
#   ./rotate-intermediate-ca.sh --root-ca-key /path/to/root_ca.key
#   ./rotate-intermediate-ca.sh --root-ca-key /path/to/root_ca.key \
#       --root-ca-password-file /path/to/root_ca.pass \
#       --password-out /media/usb/intermediate-ca.pass
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# ── 호스트별 상수 ──────────────────────────────────────────────────────────
HOST="lightsail-nixos-headscale"
TRUST_ANCHOR_ID="77dd2115-b7a2-4490-b15b-db5f4709c4e5"
AWS_REGION="ap-northeast-2"
SERVER="ec2-user@3.34.148.209"
SERVER_SSH_KEY="$HOME/.ssh/rnixup/${HOST}.pem"
ACME_DOMAIN="r.772610158.xyz"
VALIDITY="87600h"  # 10년
# ───────────────────────────────────────────────────────────────────────────

ROOT_CA_CRT="$SCRIPT_DIR/${HOST}.root-ca.crt"
INTERMEDIATE_CRT="$SCRIPT_DIR/${HOST}.intermediate-ca.crt"

ROOT_CA_KEY=""
ROOT_CA_PASSWORD_FILE=""
PASSWORD_OUT="$SCRIPT_DIR/intermediate-ca-password-$(date +%Y%m%d).txt"

usage() {
  cat <<EOF
Usage: $0 --root-ca-key <path> [options]

  --root-ca-key <path>           root CA 개인키 (필수)
  --root-ca-password-file <path> root CA 키 패스워드 파일 (암호화된 경우)
  --password-out <path>          새 패스워드 저장 경로
                                 (기본: ./intermediate-ca-password-YYYYMMDD.txt)
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --root-ca-key)           ROOT_CA_KEY="$2";           shift 2 ;;
    --root-ca-password-file) ROOT_CA_PASSWORD_FILE="$2"; shift 2 ;;
    --password-out)          PASSWORD_OUT="$2";          shift 2 ;;
    *) usage ;;
  esac
done

[[ -z "$ROOT_CA_KEY" ]]   && usage
[[ ! -f "$ROOT_CA_KEY" ]] && { echo "오류: root CA 키 파일 없음: $ROOT_CA_KEY"; exit 1; }
[[ ! -f "$ROOT_CA_CRT" ]] && { echo "오류: root CA 인증서 없음: $ROOT_CA_CRT"; exit 1; }

for cmd in step aws python3 ssh scp; do
  command -v "$cmd" &>/dev/null || { echo "오류: $cmd 설치 필요"; exit 1; }
done

NEW_KEY="$(mktemp /tmp/intermediate_ca.key.XXXXXX)"
NEW_PASS="$(mktemp /tmp/intermediate_ca.pass.XXXXXX)"
trap 'rm -f "$NEW_KEY" "$NEW_PASS"' EXIT

# ── 1. 패스워드 자동 생성 ─────────────────────────────────────────────────
echo "==> [1/6] 패스워드 생성 중..."
openssl rand -base64 32 | tr -d '\n' > "$NEW_PASS"

# ── 2. Intermediate CA 재발급 ─────────────────────────────────────────────
echo "==> [2/6] Intermediate CA 재발급 중..."
CREATE_ARGS=(
  --profile intermediate-ca
  --ca "$ROOT_CA_CRT"
  --ca-key "$ROOT_CA_KEY"
  --password-file "$NEW_PASS"
  --not-after "$VALIDITY"
  --force
)
[[ -n "$ROOT_CA_PASSWORD_FILE" ]] && CREATE_ARGS+=(--ca-password-file "$ROOT_CA_PASSWORD_FILE")

step certificate create "${CREATE_ARGS[@]}" \
  "${HOST} Intermediate CA" \
  "$INTERMEDIATE_CRT" \
  "$NEW_KEY"

echo ""
step certificate inspect "$INTERMEDIATE_CRT" | grep -E "Subject:|Not (Before|After):"

# ── 3. Trust Anchor 교체 (로컬 AWS 자격증명 사용) ─────────────────────────
echo ""
echo "==> [3/6] Trust Anchor 교체 중..."
JSON=$(python3 -c "
import json
cert = open('$INTERMEDIATE_CRT').read()
print(json.dumps({
  'trustAnchorId': '$TRUST_ANCHOR_ID',
  'source': {
    'sourceType': 'CERTIFICATE_BUNDLE',
    'sourceData': {'x509CertificateData': cert}
  }
}))
")
AWS_DEFAULT_REGION="$AWS_REGION" \
aws rolesanywhere update-trust-anchor --cli-input-json "$JSON" \
  --query 'trustAnchor.updatedAt' --output text

# ── 4. 서버에 키·패스워드 배포 ───────────────────────────────────────────
echo ""
echo "==> [4/6] 서버에 키·패스워드 배포 중..."
scp -i "$SERVER_SSH_KEY" "$NEW_KEY"  "${SERVER}:/tmp/intermediate_ca.key.new"
scp -i "$SERVER_SSH_KEY" "$NEW_PASS" "${SERVER}:/tmp/intermediate_ca.pass.new"
ssh -i "$SERVER_SSH_KEY" "$SERVER" bash <<'ENDSSH'
set -euo pipefail
sudo mv /tmp/intermediate_ca.key.new  /var/lib/step-ca-secrets/intermediate_ca.key
sudo mv /tmp/intermediate_ca.pass.new /var/lib/step-ca-secrets/password
sudo chmod 600 /var/lib/step-ca-secrets/intermediate_ca.key \
               /var/lib/step-ca-secrets/password
ENDSSH

# ── 5. git commit + push → 서버 nixup ────────────────────────────────────
echo ""
echo "==> [5/6] 코드 배포 및 서버 적용 중..."
git -C "$REPO_ROOT" add "$INTERMEDIATE_CRT"
git -C "$REPO_ROOT" commit -m "chore(${HOST}): rotate intermediate CA"
git -C "$REPO_ROOT" push

ssh -i "$SERVER_SSH_KEY" "$SERVER" bash <<ENDSSH
set -euo pipefail
cd ~/nixos
git pull --ff-only

echo "    nixup 실행 중..."
nixup os

echo "    step-ca 재시작..."
sudo systemctl restart step-ca
sleep 3
sudo systemctl is-active step-ca

echo "    ACME 인증서 재발급 중..."
sudo systemctl start --wait acme-${ACME_DOMAIN}.service
ENDSSH

# ── 6. 검증 + 패스워드 로컬 저장 ─────────────────────────────────────────
echo ""
echo "==> [6/6] 검증 중..."
ssh -i "$SERVER_SSH_KEY" "$SERVER" \
  "aws sts get-caller-identity --query '{Account:Account,Role:Arn}' --output table"

cp "$NEW_PASS" "$PASSWORD_OUT"
chmod 600 "$PASSWORD_OUT"

echo ""
echo "완료."
echo "패스워드 저장 위치: $PASSWORD_OUT"
echo "오프라인 드라이브에 백업 후 로컬에서 삭제 권장:"
echo "  rm -f $PASSWORD_OUT"
