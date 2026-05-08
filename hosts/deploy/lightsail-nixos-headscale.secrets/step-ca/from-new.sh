#!/usr/bin/env bash
# step-ca 시크릿 fetch — Intermediate CA 신규 발급
#
# root CA 개인키로 새 Intermediate CA를 발급한다.
# 발급된 인증서(공개)는 레포의 hosts/deploy/*.intermediate-ca.crt 에 자동 갱신된다.
#
# 사전 조건: step CLI  (nix-shell -p step-cli)
#
# ⚠  발급 후 AWS IAM Roles Anywhere Trust Anchor를 수동으로 교체해야 한다.
#    aws rolesanywhere update-trust-anchor \
#      --trust-anchor-id 77dd2115-b7a2-4490-b15b-db5f4709c4e5 \
#      --source sourceType=CERTIFICATE_BUNDLE,sourceData={x509CertificateData="$(cat *.intermediate-ca.crt)"}
#
# $1 = staging 디렉터리
set -euo pipefail

SECRETS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAGING="$1"

HOST="lightsail-nixos-headscale"
ROOT_CA_CRT="$SECRETS_DIR/${HOST}.root-ca.crt"
INTERMEDIATE_CRT="$SECRETS_DIR/${HOST}.intermediate-ca.crt"
VALIDITY="87600h"  # 10년

command -v step &>/dev/null || {
    printf '오류: step CLI가 필요합니다. nix-shell -p step-cli 후 재실행하세요.\n'
    exit 1
}
command -v openssl &>/dev/null || { printf '오류: openssl이 필요합니다.\n'; exit 1; }
[ -f "$ROOT_CA_CRT" ] || { printf '오류: root CA 인증서 없음: %s\n' "$ROOT_CA_CRT"; exit 1; }

printf '\n=== step-ca Intermediate CA 신규 발급 ===\n\n'

ROOT_CA_KEY=""
while true; do
    printf '  [root CA] 개인키 파일 경로 (Tab 완성): '
    read -re ROOT_CA_KEY
    ROOT_CA_KEY="${ROOT_CA_KEY/#\~/$HOME}"
    [ -f "$ROOT_CA_KEY" ] && break
    printf '  오류: 파일 없음: %s\n' "$ROOT_CA_KEY"
done

printf '  [root CA] 키 암호 파일 경로 (없으면 Enter): '
read -re ROOT_CA_PASS_FILE
ROOT_CA_PASS_FILE="${ROOT_CA_PASS_FILE/#\~/$HOME}"

NEW_KEY="$(mktemp /tmp/intermediate_ca.key.XXXXXX)"
NEW_PASS="$(mktemp /tmp/intermediate_ca.pass.XXXXXX)"
trap 'rm -f "$NEW_KEY" "$NEW_PASS"' EXIT

printf '\n==> 패스워드 생성 중...\n'
openssl rand -base64 32 | tr -d '\n' > "$NEW_PASS"

printf '==> Intermediate CA 발급 중...\n'
CREATE_ARGS=(
    --profile intermediate-ca
    --ca "$ROOT_CA_CRT"
    --ca-key "$ROOT_CA_KEY"
    --password-file "$NEW_PASS"
    --not-after "$VALIDITY"
    --force
)
[ -f "$ROOT_CA_PASS_FILE" ] && CREATE_ARGS+=(--ca-password-file "$ROOT_CA_PASS_FILE")

step certificate create "${CREATE_ARGS[@]}" \
    "${HOST} Intermediate CA" \
    "$INTERMEDIATE_CRT" \
    "$NEW_KEY"

printf '\n'
step certificate inspect "$INTERMEDIATE_CRT" | grep -E "Subject:|Not (Before|After):"

mkdir -p "$STAGING/var/lib/nix-secrets/step-ca"
cp "$NEW_KEY"  "$STAGING/var/lib/nix-secrets/step-ca/intermediate_ca.key"
cp "$NEW_PASS" "$STAGING/var/lib/nix-secrets/step-ca/password"
chmod 600 "$STAGING/var/lib/nix-secrets/step-ca/intermediate_ca.key" \
          "$STAGING/var/lib/nix-secrets/step-ca/password"

printf '\n완료.\n'
printf '  레포 갱신됨: hosts/deploy/%s.intermediate-ca.crt\n' "$HOST"
printf '  ⚠  Trust Anchor를 AWS에서 수동 교체해야 합니다.\n'
