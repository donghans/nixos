#!/usr/bin/env bash
# 격리 개발 VM(devbr0)을 일회용으로 만들고 지우는 호스트용 스크립트 (plan dev-sandbox-pilot §11, 로드맵 P6)
#
#   devvm.sh create [NAME] [--no-cache] [--no-token] [--no-home]   골든 이미지에서 새 VM 생성(기본 이름 devvm-YYMMDD-HHMM)
#   devvm.sh bundle NAME                               VM 안 저장소를 git bundle 로 호스트에 꺼냄(지우기 전 규율)
#   devvm.sh destroy NAME [--force] [--discard-dirty]  번들을 먼저 꺼내고 지움(번들 실패·미커밋 변경 있으면 거부)
#   devvm.sh golden [SRC_INSTANCE]                     SRC(기본 dev-nixos)를 정상 종료 후 복제해 골든(devvm-golden@gold)을 새로 만듦
#   devvm.sh list                                      devvm-* VM 목록
#
# 전제·한계
#  - 호스트(msi-summit-me) 전용: incus 사용 권한, devbr0 브리지, nix-serve(10.100.1.1:5000) 필요.
#  - 제어 채널은 incus exec(에이전트) — ssh 로의 전환은 별도 단계(plan §11).
#  - 캐시 등록은 VM 의 /etc/nix/nix.conf 심볼릭 링크를 파일로 바꾸는 방식이라 VM 안에서 `nixup`(시스템 적용)을 하면 되돌아간다.
#    그때는 `devvm.sh cache NAME` 으로 다시 등록한다.
#  - 토큰은 VM 의 tmpfs(/run/devvm-claude/token)에만 둔다(재부팅하면 사라짐). 값은 명령줄·디스크에 남기지 않는다.
set -euo pipefail

GOLDEN_INST="devvm-golden"   # 정지 상태로만 둔다. 스냅샷 gold 가 복제 원본
GOLDEN_SNAP="gold"
GOLDEN_SRC_DEFAULT="${DEVVM_GOLDEN_SRC:-dev-nixos}"
NETWORK="devbr0"
CACHE_URL="http://10.100.1.1:5000"
CACHE_KEY_DEFAULT="devbr0-nix-serve:V+CdKcL1BZ5sgn4t7xsRsffYkG11gkjcqRThEp51034="
CACHE_PUB_FILE="/var/lib/nix-serve-devbr0/cache-pub-key.pem"
VM_USER="devvm"
VM_UID=1001
VM_GID=100
VM_HOME="/home/$VM_USER"
VM_REPO="$VM_HOME/nixos"
TOKEN_PATH="/run/devvm-claude/token"
BUNDLE_DIR="${DEVVM_BUNDLE_DIR:-$HOME/.local/share/devvm/bundles}"
# 골든에 처음부터 있는 파일(nixstrap 이 만든 호스트 파일·nixup 이 매번 건드리는 락)은 「미커밋 변경」으로 세지 않는다
DIRTY_IGNORE="${DEVVM_DIRTY_IGNORE:-^(( M)|(\?\?)) (\.locks/_rolling\.lock|hosts/dev-nixos\.(nix|toml))$}"
VM_PATH="/run/current-system/sw/bin:/bin" # incus exec 의 PATH 는 비어 있다(함정)

AUDIT_LOG="${DEVVM_AUDIT_LOG:-$HOME/.local/state/devvm/audit.log}"

# 감사 기록: 한 줄 JSON(시각·이벤트·VM·상세)을 남기고 데스크톱 알림을 보낸다(앱 이름 `devvm` — 알림 센터 `notif` 에 모인다).
# 수준: info(생성·삭제·번들 등 평시 기록) / critical(실패·--force 같이 눈에 띄어야 하는 것 — 알림 센터의 「시스템 문제」로 분류됨).
# 비밀 값은 넣지 않는다(토큰은 「주입했다」는 사실과 바이트 수만).
audit() { # audit LEVEL EVENT NAME DETAIL
    local level=$1 event=$2 name=${3:-} detail=${4:-}
    mkdir -p "$(dirname "$AUDIT_LOG")"
    python3 -c 'import json,sys,time;print(json.dumps({"ts":time.strftime("%Y-%m-%dT%H:%M:%S%z"),"level":sys.argv[1],"event":sys.argv[2],"vm":sys.argv[3],"detail":sys.argv[4]},ensure_ascii=False))' \
        "$level" "$event" "$name" "$detail" >>"$AUDIT_LOG" 2>/dev/null || true
    if command -v notify-send >/dev/null 2>&1; then
        local urg=normal; [[ $level == critical ]] && urg=critical
        notify-send -a devvm -u "$urg" "devvm $event${name:+: $name}" "$detail" >/dev/null 2>&1 || true
    fi
}

die() { printf 'devvm: %s\n' "$*" >&2; audit critical error "${DEVVM_CUR:-}" "$*"; exit 1; }
say() { printf 'devvm: %s\n' "$*" >&2; }

vmx() { # vmx NAME CMD… — VM 안에서 root 로 실행
    local name=$1; shift
    incus exec "$name" --env "PATH=$VM_PATH" -- "$@"
}
vmu() { # vmu NAME CMD… — VM 안에서 devvm 사용자로 실행
    local name=$1; shift
    incus exec "$name" --user "$VM_UID" --group "$VM_GID" --env "HOME=$VM_HOME" --env "PATH=$VM_PATH" -- "$@"
}

check_name() {
    DEVVM_CUR=${1:-}
    [[ "${1:-}" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "VM 이름이 필요합니다(소문자·숫자·하이픈)"
    # 사람이 쓰는 상시 VM·다른 인스턴스를 실수로 건드리지 않게 devvm- 접두사만 허용
    [[ "$1" != "$GOLDEN_INST" ]] || die "$GOLDEN_INST 는 골든 원본이라 이 명령으로 다루지 않습니다"
    [[ "$1" == devvm-* ]] || die "이 스크립트는 devvm- 로 시작하는 VM 만 다룹니다(받은 이름: $1)"
}

wait_agent() {
    local name=$1
    for _ in $(seq 1 90); do
        if vmx "$name" true >/dev/null 2>&1; then return 0; fi
        sleep 2
    done
    die "$name 의 에이전트가 180초 안에 응답하지 않았습니다"
}

cmd_golden() {
    local src=${1:-$GOLDEN_SRC_DEFAULT}
    # 이미지 게시(incus publish)는 쓰지 않는다: 2026-11-22 시험에서 이미지로 만든 VM 의 nix 스토어 파일 일부가 0바이트로 깨졌다
    # (하드링크 파일). 또 실행 중인 VM 의 스냅샷은 디스크에 안 내려간 쓰기가 빠져 같은 증상이 난다 → 반드시 정상 종료 뒤 복제.
    incus info "$src" >/dev/null 2>&1 || die "원본 인스턴스 $src 가 없습니다"
    incus info "$GOLDEN_INST" >/dev/null 2>&1 && die "$GOLDEN_INST 가 이미 있습니다 — 새로 만들려면 'incus delete -f $GOLDEN_INST' 를 먼저(파괴적이라 직접)"
    local was_running=0
    [[ $(incus list "$src" -f csv -c s) == RUNNING ]] && was_running=1
    ((was_running)) && { say "$src 정상 종료(복제 일관성)"; incus stop "$src"; }
    incus copy "$src" "$GOLDEN_INST" --instance-only
    ((was_running)) && incus start "$src"
    # 인증정보·작업 잔재 정리 후 스냅샷: 골든은 한 번 켜서 정리하고 끈다
    incus start "$GOLDEN_INST"; wait_agent "$GOLDEN_INST"
    vmx "$GOLDEN_INST" sh -c "rm -f $VM_HOME/.claude/history.jsonl; sync"
    incus stop "$GOLDEN_INST"
    incus snapshot create "$GOLDEN_INST" "$GOLDEN_SNAP"
    audit info golden "$GOLDEN_INST" "$src 정상 종료 복제 → $GOLDEN_INST@$GOLDEN_SNAP"
}

cmd_cache() {
    local name=$1 key=$CACHE_KEY_DEFAULT
    check_name "$name"
    if [[ -r $CACHE_PUB_FILE ]]; then
        key=$(<"$CACHE_PUB_FILE")
        [[ $key == "$CACHE_KEY_DEFAULT" ]] || say "주의: 호스트 공개키가 기본값과 다릅니다 — 호스트 키($CACHE_PUB_FILE)를 씁니다"
    fi
    # nix.conf 는 /etc/static 으로의 심볼릭 링크(읽기 전용) — 파일로 바꾸고 extra-* 한 줄씩 덧붙인다. 이미 있으면 건너뜀.
    # shellcheck disable=SC2016  # 작은따옴표 안의 $1·$2 는 VM 쪽 셸이 펼친다
    vmx "$name" sh -c '
        set -e
        conf=/etc/nix/nix.conf
        [ -L "$conf" ] && cp --remove-destination "$(readlink -f "$conf")" "$conf" && chmod 644 "$conf"
        grep -qF "$1" "$conf" || printf "extra-substituters = %s\n" "$1" >> "$conf"
        grep -qF "$2" "$conf" || printf "extra-trusted-public-keys = %s\n" "$2" >> "$conf"
        systemctl restart nix-daemon
    ' sh "$CACHE_URL" "$key"
    # 접근 확인: VM → 캐시
    if vmx "$name" curl -sf --max-time 10 "$CACHE_URL/nix-cache-info" >/dev/null; then
        say "캐시 등록·접근 확인 완료($CACHE_URL)"
        audit info cache "$name" "$CACHE_URL 등록·접근 확인"
    else
        die "캐시 등록은 했으나 VM 에서 $CACHE_URL 에 닿지 않습니다(호스트 nix-serve·devbr0-guard 확인)"
    fi
}

cmd_home() {
    local name=$1
    check_name "$name"
    # 골든에는 홈 프로필이 이미 있어 보통 몇 초 안에 끝난다. 실패해도 생성 전체를 막지는 않고 critical 로 알린다.
    if vmu "$name" sh -c "cd $VM_REPO && USER=$VM_USER nixup home" >/dev/null 2>&1; then
        vmu "$name" test -x "$VM_HOME/.nix-profile/bin/claude" || { audit critical home "$name" "nixup home 은 끝났으나 claude 가 없음"; return 0; }
        audit info home "$name" "nixup home 완료, claude 확인"
    else
        audit critical home "$name" "nixup home 실패 — VM 안에서 직접 확인 필요"
    fi
}

cmd_token() {
    local name=$1
    check_name "$name"
    command -v donghans >/dev/null || die "donghans 명령이 없습니다"
    # 값은 환경변수 → 표준입력으로만 흐른다(명령줄에 없음). 파일은 VM tmpfs, 0600, devvm 소유.
    # shellcheck disable=SC2016  # $VM_CLAUDE_TOKEN·$1.. 는 donghans secret run 이 띄운 셸이 펼친다(명령줄에 값이 없게)
    donghans secret run --env VM_CLAUDE_TOKEN -- sh -c '
        printf %s "$VM_CLAUDE_TOKEN" | incus exec "$1" --env PATH="$2" -- sh -c "
            set -e; umask 077; mkdir -p /run/devvm-claude; cat > $3
            chown -R $4:$5 /run/devvm-claude; chmod 700 /run/devvm-claude"
    ' sh "$name" "$VM_PATH" "$TOKEN_PATH" "$VM_UID" "$VM_GID"
    local bytes
    bytes=$(vmx "$name" sh -c "wc -c < $TOKEN_PATH")
    [[ ${bytes//[[:space:]]/} -gt 20 ]] || die "토큰 파일이 비어 있거나 너무 짧습니다(${bytes}바이트)"
    audit info token "$name" "VM_CLAUDE_TOKEN 주입(tmpfs, ${bytes//[[:space:]]/}바이트)"
    say "토큰 주입 완료(tmpfs $TOKEN_PATH, ${bytes//[[:space:]]/}바이트, 값은 출력하지 않음)"
}

cmd_create() {
    local name="" cache=1 token=1 home=1
    while (($#)); do
        case $1 in
            --no-cache) cache=0 ;;
            --no-token) token=0 ;;
            --no-home) home=0 ;;
            -*) die "알 수 없는 옵션: $1" ;;
            *) name=$1 ;;
        esac
        shift
    done
    [[ -n $name ]] || name="devvm-$(date +%y%m%d-%H%M)"
    check_name "$name"
    incus info "$GOLDEN_INST" >/dev/null 2>&1 || die "골든 $GOLDEN_INST 가 없습니다 — 먼저 'devvm.sh golden'"
    incus info "$name" >/dev/null 2>&1 && die "$name 은 이미 있습니다"
    incus network show "$NETWORK" >/dev/null 2>&1 || die "브리지 $NETWORK 가 없습니다"

    say "생성: $name ← $GOLDEN_INST@$GOLDEN_SNAP (스냅샷 복제, vmx 마스킹 켬 = 중첩 가상화 기본 꺼짐)"
    incus copy "$GOLDEN_INST/$GOLDEN_SNAP" "$name" >/dev/null 2>&1 || die "incus copy 실패($name)"
    incus config set "$name" raw.qemu="-cpu host,-vmx"
    incus config device get "$name" eth0 network 2>/dev/null | grep -qx "$NETWORK" || die "$name 의 eth0 가 $NETWORK 에 붙어 있지 않습니다"
    incus start "$name"
    wait_agent "$name"
    # 골든은 같은 호스트명·머신 ID 를 물려받는다 — 같은 시기에 여러 대를 띄워도 DHCP 는 MAC 으로 구분되므로 두고 간다.

    ((home)) && cmd_home "$name"
    ((cache)) && cmd_cache "$name"
    ((token)) && cmd_token "$name"

    local ip
    ip=$(incus list "$name" -f json | python3 -c 'import sys,json
d=json.load(sys.stdin)[0]["state"]["network"]
print(" ".join(a["address"] for a in d.get("eth0",{}).get("addresses",[]) if a["family"]=="inet"))')
    audit info create "$name" "골든 $GOLDEN_INST@$GOLDEN_SNAP 에서 생성, $ip, vmx 마스킹 켬"
    say "완료: $name  ($ip)"
    say "Claude 는 VM 안에서: CLAUDE_CODE_OAUTH_TOKEN=\$(cat $TOKEN_PATH) claude"
}

cmd_bundle() {
    local name=${1:-} force=${2:-}
    check_name "$name"
    [[ $(incus list "$name" -f csv -c s) == RUNNING ]] || die "$name 이 실행 중이 아니라 번들을 꺼낼 수 없습니다"
    vmu "$name" test -d "$VM_REPO/.git" || die "$VM_REPO 에 저장소가 없습니다"
    mkdir -p "$BUNDLE_DIR"
    local out
    out="$BUNDLE_DIR/$name-$(date +%y%m%d-%H%M%S).bundle"
    # 미커밋 변경은 번들에 안 들어간다 — 있으면 알린다(destroy 는 이것으로 거부)
    local dirty
    dirty=$(vmu "$name" git -C "$VM_REPO" status --porcelain 2>/dev/null | grep -Ev "$DIRTY_IGNORE" || true)
    if [[ -n $dirty ]]; then
        say "미커밋 변경 $(wc -l <<<"$dirty")건 — 번들에 들어가지 않습니다:"
        head -20 <<<"$dirty" | while IFS= read -r l; do printf '    %s\n' "$l"; done >&2
        DEVVM_DIRTY=1
    fi
    vmu "$name" git -C "$VM_REPO" bundle create - --all >"$out" 2>/dev/null || { rm -f "$out"; die "번들 생성 실패"; }
    [[ -s $out ]] || { rm -f "$out"; die "번들이 비었습니다"; }
    (cd "$(dirname "$(readlink -f "$0")")/../.." && git bundle verify "$out" >/dev/null 2>&1) \
        || { say "경고: 호스트 저장소에서 verify 실패 — 번들은 남깁니다: $out"; }
    audit info bundle "$name" "$out"
    say "번들 저장: $out ($(du -h "$out" | cut -f1))"
    BUNDLE_OUT=$out
}

cmd_destroy() {
    local name="" force=0 discard=0
    while (($#)); do
        case $1 in
            --force) force=1 ;;
            --discard-dirty) discard=1 ;;
            -*) die "알 수 없는 옵션: $1" ;;
            *) name=$1 ;;
        esac
        shift
    done
    check_name "$name"
    incus info "$name" >/dev/null 2>&1 || die "$name 이 없습니다"
    DEVVM_DIRTY=0
    if ((force)); then
        say "--force: 번들 없이 지웁니다"
    else
        cmd_bundle "$name"
        if ((DEVVM_DIRTY)) && ((!discard)); then
            die "미커밋 변경이 있어 지우지 않습니다 — VM 안에서 커밋 후 다시 하거나 --discard-dirty (번들은 $BUNDLE_OUT 에 저장됨)"
        fi
    fi
    incus delete -f "$name"
    if ((force)); then
        audit critical destroy "$name" "--force: 번들 없이 삭제"
    else
        audit info destroy "$name" "번들 ${BUNDLE_OUT:-없음} 저장 후 삭제"
    fi
    say "삭제 완료: $name"
}

cmd_list() { incus list '^devvm-' -c ns4 -f compact; }

case "${1:-}" in
    create) shift; cmd_create "$@" ;;
    bundle) shift; cmd_bundle "${1:-}" ;;
    destroy) shift; cmd_destroy "$@" ;;
    golden) shift; cmd_golden "$@" ;;
    cache) shift; cmd_cache "${1:-}" ;;
    token) shift; cmd_token "${1:-}" ;;
    home) shift; cmd_home "${1:-}" ;;
    list) cmd_list ;;
    *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2 ;;
esac
