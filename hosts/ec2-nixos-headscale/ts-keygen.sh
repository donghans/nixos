#!/usr/bin/env nix-shell
#!nix-shell -i bash -I nixpkgs=flake:nixpkgs -p age gh jq
# ts-keygen.sh — tailscale machine key 생성 + nixsec 업로드
#
# secrets.json에서 ts-state 항목을 자동 스캔하고 _check UI로 처리할 항목 선택.
# EC2에서 임시 tailscaled를 실행해 state 파일(Ed25519 machine key)을 생성한다.
set -euo pipefail

EC2_IP="43.201.166.32"
EC2_SSH_KEY="${HOME}/.ssh/rnixup/ec2-nixos-headscale.pem"
EC2_USER="ec2-user"
REPO="donghans/aws-headscale-secrets"

NIXOS_PATH="$(readlink -f "$(dirname "$0")/../..")"
SSH_OPTS="-i $EC2_SSH_KEY -o StrictHostKeyChecking=no -o BatchMode=yes -o LogLevel=ERROR"

source "$NIXOS_PATH/core/scripts/nixup.lib-ui.sh"
_LOG_PREFIX="KEYGEN"
source "$NIXOS_PATH/core/scripts/nixsec.task-upload.sh"

# ── secrets.json에서 ts-state 항목 자동 스캔 ──────────────────────────────────
# 레포 경로가 ts-state 또는 tailscaled.state로 끝나는 항목 수집
mapfile -t _ALL_PATHS < <(
    find "$NIXOS_PATH/hosts/deploy" -name "secrets.json" -print0 \
        | xargs -0 jq -r '
            .groups[].secrets
            | to_entries[]
            | select(.key | test("ts-state$|tailscaled\\.state$"))
            | .key
        ' 2>/dev/null | sort -u
)

if [ "${#_ALL_PATHS[@]}" -eq 0 ]; then
    log_msg "Error" "ts-state 항목을 찾을 수 없습니다."
    exit 1
fi

# ── 각 항목의 레포 존재 여부 확인 ────────────────────────────────────────────
log_msg "Task" "레포 상태 확인 중..."
declare -a _CHECK_ARGS=()
for _path in "${_ALL_PATHS[@]}"; do
    if gh api "repos/$REPO/contents/${_path}.age" --jq '.sha' &>/dev/null 2>&1; then
        _CHECK_ARGS+=("$_path" "${_path}  [있음]")
    else
        _CHECK_ARGS+=("$_path" "${_path}  [없음 — 생성 필요]")
    fi
done

# ── _check UI로 처리할 항목 선택 ─────────────────────────────────────────────
printf "\n"
_check "처리할 항목을 선택하세요 (Space 토글, Enter 확인)" "${_CHECK_ARGS[@]}"

if [ "${#REPLY_CHECKED[@]}" -eq 0 ]; then
    log_msg "Notice" "선택된 항목 없음. 종료합니다."
    exit 0
fi

# ── pubkey 조회 (공통) ────────────────────────────────────────────────────────
PUBKEY=$(gh api "repos/$REPO/contents/.pubkey" --jq '.content' | base64 -d | tr -d '\n') \
    || { log_msg "Error" ".pubkey 조회 실패 — nixsec 초기화 완료 여부 확인"; exit 1; }

# ── 선택된 항목 처리 ──────────────────────────────────────────────────────────
for REMOTE_PATH in "${REPLY_CHECKED[@]}"; do
    printf "\n"
    log_msg "Task" "[$REMOTE_PATH] 처리 중..."

    # EC2에서 임시 tailscaled 실행 → state 파일 생성
    EC2_STATE_TMP="/tmp/ts-keygen-$$.state"
    EC2_SOCK="/tmp/ts-keygen-$$.sock"
    LOCAL_TMP=$(mktemp /tmp/ts-keygen-state.XXXXXX)
    chmod 600 "$LOCAL_TMP"
    trap 'rm -f "$LOCAL_TMP"; ssh '"$SSH_OPTS"' '"${EC2_USER}@${EC2_IP}"' "sudo rm -f '"$EC2_STATE_TMP $EC2_SOCK"'" 2>/dev/null || true' EXIT

    ssh $SSH_OPTS "${EC2_USER}@${EC2_IP}" bash -s -- "$EC2_STATE_TMP" "$EC2_SOCK" << 'ENDSSH'
STATE="$1"; SOCK="$2"
sudo tailscaled --state="$STATE" --socket="$SOCK" --tun=userspace-networking &>/dev/null &
PID=$!
sleep 3
sudo kill "$PID" 2>/dev/null || true
wait "$PID" 2>/dev/null || true
[ -f "$STATE" ] || { echo "state 파일 생성 실패" >&2; exit 1; }
sudo chown "$(id -un)":"$(id -gn)" "$STATE"
ENDSSH

    scp $SSH_OPTS "${EC2_USER}@${EC2_IP}:${EC2_STATE_TMP}" "$LOCAL_TMP"
    ssh $SSH_OPTS "${EC2_USER}@${EC2_IP}" "sudo rm -f '$EC2_STATE_TMP' '$EC2_SOCK'" 2>/dev/null || true
    trap - EXIT

    [ -s "$LOCAL_TMP" ] || { log_msg "Error" "state 파일이 비어있습니다."; rm -f "$LOCAL_TMP"; continue; }
    log_msg "Done" "machine key 생성 완료 ($(wc -c < "$LOCAL_TMP") bytes)"

    # nixsec 업로드
    _upload_encrypted "$REPO" "$REMOTE_PATH" "$LOCAL_TMP" "$PUBKEY"
    rm -f "$LOCAL_TMP"

    # 업로드 확인
    SHA=$(gh api "repos/$REPO/contents/${REMOTE_PATH}.age" --jq '.sha' 2>/dev/null || true)
    if [ -n "$SHA" ]; then
        log_msg "Done" "업로드 확인됨 (sha: ${SHA:0:8}...)"
    else
        log_msg "Error" "[$REMOTE_PATH] 업로드 확인 실패"
    fi
done

printf "\n"
log_msg "Done" "완료."
