#!/usr/bin/env bash
# sbox — 일회용 격리 환경(sboxbr0)을 만들고 꺼내고 지우는 호스트용 스크립트 (plan dev-sandbox-pilot §11·§15, 로드맵 P6)
# 종류(--kind): vm = nixos OS 단위 시험용 VM(구현됨). ct = 프로젝트용 컨테이너(v1: debian·ubuntu — §23 S1). 종류는 필수 인자이고 기본값이 없다.
# 이름: sbox-vm-<이름> / sbox-ct-<flavor><버전(점 제거)>-<이름>(예 sbox-ct-debian13-proj), 골든은 sbox-golden-vm(VM 전용). VM 안 사용자 이름은 sbox, 호스트명은 sbox-nixos(2026-11-22 devvm·dev-nixos 에서 변경).
#
#   sbox.sh create --kind ct --flavor debian|ubuntu [--release R] [--legacy] [--nesting] [--cpu N] [--memory M] [NAME]  컨테이너 생성(v1)
#   sbox.sh releases [flavor]                          쓸 수 있는 릴리스 표(core/sbox/releases.toml)
#   sbox.sh create --kind vm [NAME] [--no-cache] [--no-token] [--no-home]   골든 이미지에서 새 VM 생성(기본 이름 sbox-vm-YYMMDD-HHMM)
#   sbox.sh tools NAME [--from-repo DIR|--manifest F] [--update] [node=22]  컨테이너에 읽기 전용 도구 층 붙임(호스트가 받아 sha256 검증, 버전은 매니페스트에 고정, v1: node)
#   sbox.sh bundle NAME                               VM 안 저장소를 git bundle 로 호스트에 꺼냄(지우기 전 규율)
#   sbox.sh import BUNDLE                             번들을 호스트 저장소의 refs/sbox/<VM>/* 로만 가져옴(병합·체크아웃 안 함) + 새 커밋 목록
#   sbox.sh destroy NAME [--force] [--discard-dirty]  번들을 먼저 꺼내고 지움(번들 실패·미커밋 변경 있으면 거부)
#   sbox.sh golden [SRC_INSTANCE]                     SRC(기본 dev-nixos)를 정상 종료 후 복제해 골든(sbox-golden-vm@gold)을 새로 만듦
#   sbox.sh rebuild-golden [--stale-ok]               ISO+nixstrap(NIXSTRAP_AUTO)로 골든을 처음부터 새로 만듦(약 15분)
#   sbox.sh list                                      sbox-* 인스턴스 목록
#   sbox.sh iso [--stale-ok]                          설치 ISO 만 미리 빌드(캐시면 약 20초, nixstrap 수정 직후면 약 7분)
#
# 전제·한계
#  - 호스트(msi-summit-me) 전용: incus 사용 권한, sboxbr0 브리지, nix-serve(10.100.1.1:5000) 필요.
#  - 제어 채널은 incus exec(에이전트) — ssh 로의 전환은 별도 단계(plan §11).
#  - 캐시 등록은 VM 의 /etc/nix/nix.conf 심볼릭 링크를 파일로 바꾸는 방식이라 VM 안에서 `nixup`(시스템 적용)을 하면 되돌아간다.
#    그때는 `sbox.sh cache NAME` 으로 다시 등록한다.
#  - 토큰은 VM 의 tmpfs(/run/sbox-claude/token)에만 둔다(재부팅하면 사라짐). 값은 명령줄·디스크에 남기지 않는다.
set -euo pipefail

GOLDEN_INST="${SBOX_GOLDEN_INST:-sbox-golden-vm}"   # 정지 상태로만 둔다. 스냅샷 gold 가 복제 원본
GOLDEN_SNAP="gold"
GOLDEN_SRC_DEFAULT="${SBOX_GOLDEN_SRC:-dev-nixos}"
NETWORK="sboxbr0"
CACHE_URL="http://10.100.1.1:5000"
CACHE_KEY_DEFAULT="devbr0-nix-serve:V+CdKcL1BZ5sgn4t7xsRsffYkG11gkjcqRThEp51034="
CACHE_PUB_FILE="/var/lib/nix-serve-devbr0/cache-pub-key.pem"
VM_USER="sbox"
VM_UID=""   # VM 마다 다르다(다시 만든 골든은 1000, 이름을 바꿔 만든 옛 골든은 1001) — resolve_ids 가 VM 안에서 조회한다
VM_GID=""
VM_IDS_FOR=""
VM_HOME="/home/$VM_USER"
VM_REPO="$VM_HOME/nixos"
TOKEN_PATH="/run/sbox-claude/token"
BUNDLE_DIR="${SBOX_BUNDLE_DIR:-$HOME/.local/share/sbox/bundles}"
# 골든에 처음부터 있는 파일(nixstrap 이 만든 호스트 파일·nixup 이 매번 건드리는 락)은 「미커밋 변경」으로 세지 않는다
DIRTY_IGNORE="${SBOX_DIRTY_IGNORE:-^(( M)|(\?\?)) (\.locks/_rolling\.lock|hosts/sbox-nixos\.(nix|toml))$}"
VM_PATH="/run/wrappers/bin:/run/current-system/sw/bin:/bin" # incus exec 의 PATH 는 비어 있다(함정)
CT_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" # 컨테이너(debian·ubuntu 등 FHS 배포판)용
EXEC_PATH="$VM_PATH"   # vmx·vmu 등이 쓰는 PATH — check_name 이 종류에 맞게 바꾼다
NAME_KIND=""           # check_name 이 vm|ct 로 채운다
SBOX_DIR="$(dirname "$(readlink -f "$0")")/../sbox"   # releases.toml·release.py

AUDIT_LOG="${SBOX_AUDIT_LOG:-$HOME/.local/state/sbox/audit.log}"

# 감사 기록: 한 줄 JSON(시각·이벤트·VM·상세)을 남기고 데스크톱 알림을 보낸다(앱 이름 `sbox` — 알림 센터 `notif` 에 모인다).
# 수준: info(생성·삭제·번들 등 평시 기록) / critical(실패·--force 같이 눈에 띄어야 하는 것 — 알림 센터의 「시스템 문제」로 분류됨).
# 비밀 값은 넣지 않는다(토큰은 「주입했다」는 사실과 바이트 수만).
audit() { # audit LEVEL EVENT NAME DETAIL
    local level=$1 event=$2 name=${3:-} detail=${4:-}
    mkdir -p "$(dirname "$AUDIT_LOG")"
    python3 -c 'import json,sys,time,os;print(json.dumps({"ts":time.strftime("%Y-%m-%dT%H:%M:%S%z"),"level":sys.argv[1],"event":sys.argv[2],"vm":sys.argv[3],"kind":("vm" if sys.argv[3].startswith(("sbox-vm-","sbox-golden-vm")) else "ct" if sys.argv[3].startswith("sbox-ct-") else ""),"flavor":os.environ.get("AUDIT_FLAVOR",""),"release":os.environ.get("AUDIT_RELEASE",""),"eol":os.environ.get("AUDIT_EOL",""),"detail":sys.argv[4]},ensure_ascii=False))' \
        "$level" "$event" "$name" "$detail" >>"$AUDIT_LOG" 2>/dev/null || true
    if command -v notify-send >/dev/null 2>&1; then
        local urg=normal; [[ $level == critical ]] && urg=critical
        notify-send -a sbox -u "$urg" "sbox $event${name:+: $name}" "$detail" >/dev/null 2>&1 || true
    fi
}

die() { printf 'sbox: %s\n' "$*" >&2; audit critical error "${SBOX_CUR:-}" "$*"; exit 1; }
say() { printf 'sbox: %s\n' "$*" >&2; }

vmx() { # vmx NAME CMD… — VM 안에서 root 로 실행
    local name=$1; shift
    incus exec "$name" --env "PATH=$EXEC_PATH" -- "$@"
}
vmx_env() { # vmx_env NAME VAR=VAL… -- CMD… — 표준입력을 그대로 넘기며 환경변수를 주고 root 로 실행
    local name=$1; shift
    local -a envs=(--env "PATH=$EXEC_PATH")
    while [[ ${1:-} != -- ]]; do envs+=(--env "$1"); shift; done
    shift
    incus exec "$name" "${envs[@]}" -- "$@"
}
resolve_ids() { # resolve_ids NAME — VM 안 sbox 사용자의 uid·gid 를 조회해 둔다(VM 별 1회)
    [[ $VM_IDS_FOR == "$1" ]] && return 0
    VM_UID=$(incus exec "$1" --env "PATH=$EXEC_PATH" -- id -u "$VM_USER") || die "$1 에서 사용자 $VM_USER 를 찾지 못했습니다"
    VM_GID=$(incus exec "$1" --env "PATH=$EXEC_PATH" -- id -g "$VM_USER")
    VM_IDS_FOR=$1
}
vmu() { # vmu NAME CMD… — VM 안에서 sbox 사용자로 실행
    local name=$1; shift
    resolve_ids "$name"
    local -a extra=()
    [[ -n ${NIX_CFG:-} ]] && extra=(--env "NIX_CONFIG=$NIX_CFG")
    incus exec "$name" --user "$VM_UID" --group "$VM_GID" --env "HOME=$VM_HOME" --env "PATH=$EXEC_PATH" "${extra[@]}" -- "$@"
}

check_name() {
    SBOX_CUR=${1:-}
    [[ "${1:-}" =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "인스턴스 이름이 필요합니다(소문자·숫자·하이픈)"
    [[ "$1" != "$GOLDEN_INST" ]] || die "$GOLDEN_INST 는 골든 원본이라 이 명령으로 다루지 않습니다"
    # 사람이 쓰는 상시 VM·다른 인스턴스를 실수로 건드리지 않게 sbox-vm-·sbox-ct- 접두사만 허용. 종류별 정책은 이름에서 정해진다(plan §15 조건 ②).
    case "$1" in
        sbox-vm-*) NAME_KIND=vm; EXEC_PATH=$VM_PATH ;;
        sbox-ct-*) NAME_KIND=ct; EXEC_PATH=$CT_PATH ;;
        *) die "이 스크립트는 sbox-vm-<이름>·sbox-ct-<flavor><버전>-<이름> 인스턴스만 다룹니다(받은 이름: $1)" ;;
    esac
}

require_vm() { [[ $NAME_KIND == vm ]] || die "이 명령은 vm 종류(nixos) 전용입니다 — $SBOX_CUR 는 $NAME_KIND"; }

wait_agent() {
    local name=$1 ok=0
    for _ in $(seq 1 90); do
        if vmx "$name" true >/dev/null 2>&1; then ok=1; break; fi
        sleep 2
    done
    ((ok)) || die "$name 의 에이전트가 180초 안에 응답하지 않았습니다"
    # 에이전트는 DHCP 보다 먼저 응답한다 — 기본 경로(=네트워크)가 생길 때까지 최대 60초 더 기다린다
    for _ in $(seq 1 30); do
        vmx "$name" sh -c 'ip route 2>/dev/null | grep -q "^default"' >/dev/null 2>&1 && return 0
        sleep 2
    done
    die "$name 의 네트워크(기본 경로)가 60초 안에 올라오지 않았습니다"
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

build_iso() { # build_iso STALE_OK — ISO 를 빌드(변경 없으면 캐시)하고 경로를 ISO_PATH 에 둔다
    local stale_ok=$1 repo build_dir=${XDG_CACHE_HOME:-$HOME/.cache}/nixos/build
    repo=$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)
    # 빌드 사본(.build 는 nixup 이 만든 사본)이 낡았으면 ISO 의 nixstrap 도 낡다 — 먼저 `nixup check` 로 갱신
    if ((!stale_ok)) && ! diff -q "$build_dir/core/scripts/nixstrap.sh" "$repo/core/scripts/nixstrap.sh" >/dev/null 2>&1; then
        die "빌드 사본($build_dir)의 nixstrap.sh 가 저장소와 다릅니다 — 'nixup check' 로 갱신하거나 --stale-ok"
    fi
    if ((!stale_ok)) && ! diff -q "$build_dir/core/scripts/nixstrap.task-install.sh" "$repo/core/scripts/nixstrap.task-install.sh" >/dev/null 2>&1; then
        die "빌드 사본($build_dir)의 nixstrap.task-install.sh 가 저장소와 다릅니다 — 'nixup check' 로 갱신하거나 --stale-ok"
    fi
    local t0=$SECONDS iso_link=${XDG_CACHE_HOME:-$HOME/.cache}/nixos/dev-iso
    say "ISO 빌드(변경 없으면 캐시)"
    nix build "path:$build_dir#nixosConfigurations.custom-iso.config.system.build.isoImage" --impure --out-link "$iso_link" >&2 \
        || die "ISO 빌드 실패"
    ISO_PATH=$(find "$(readlink -f "$iso_link")/iso" -maxdepth 1 -name '*.iso' 2>/dev/null | head -1)
    [[ -r $ISO_PATH ]] || die "ISO 파일을 찾지 못했습니다($iso_link)"
    say "ISO 준비 완료($((SECONDS - t0))초): $ISO_PATH"
}

cmd_iso() { # 미리 빌드해 두면 rebuild-golden 이 ISO 대기 없이(약 20초) 시작한다. 결과는 ~/.cache/nixos/dev-iso 에 GC 루트로 남는다
    local stale_ok=0
    [[ ${1:-} == --stale-ok ]] && stale_ok=1
    build_iso "$stale_ok"
    audit info iso "" "$ISO_PATH"
}

cmd_rebuild_golden() {
    local stale_ok=0
    [[ ${1:-} == --stale-ok ]] && stale_ok=1
    incus info "$GOLDEN_INST" >/dev/null 2>&1 && die "$GOLDEN_INST 가 이미 있습니다 — 다른 이름은 SBOX_GOLDEN_INST=… 로, 교체는 'incus delete -f' 를 직접(파괴적)"
    local repo t0=$SECONDS iso
    repo=$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)
    build_iso "$stale_ok"
    iso=$ISO_PATH

    SBOX_CUR=$GOLDEN_INST
    local t_init=$SECONDS
    # incus 생성 클라이언트가 응답 없이 수십 분 멈추거나 실패한 적이 있다(2026-11-22 네 번, 원인 미확인 — 같은 이름 재사용만의 문제는 아님:
    # 새 이름으로도 재현). 오류를 숨기지 않고 보여 주며 시간 제한 후 최대 3번 재시도한다.
    local _try _err
    for _try in 1 2 3; do
        if _err=$(timeout 120 incus init --empty --vm "$GOLDEN_INST" -n "$NETWORK" -c limits.cpu=4 -c limits.memory=8GiB \
            -c security.secureboot=false -d root,size=120GiB 2>&1 </dev/null); then break; fi
        say "incus init 실패($_try/3): ${_err##*$'\n'}"
        incus delete -f "$GOLDEN_INST" >/dev/null 2>&1 || true
        sleep 10
        [[ $_try == 3 ]] && die "incus init 3회 실패($GOLDEN_INST): ${_err##*$'\n'}"
    done
    say "incus init $((SECONDS - t_init))초"
    incus config device add "$GOLDEN_INST" iso disk source="$iso" boot.priority=10 >/dev/null
    incus start "$GOLDEN_INST"
    wait_agent "$GOLDEN_INST"

    # PARAMS_FILE: 선택값을 미리 적는다(nixstrap 의 save_params 형식). 디스크 전체 삭제는 이 빈 VM 의 가상 디스크(sda)에만 적용된다.
    # 부트 영역 끝값은 호스트에서 같은 스크립트로 계산한다(ISO 의 기본 PATH 에는 python3 가 없고 nixstrap-wrapped 만 자기 PATH 에 넣어 쓴다)
    local boot_end
    boot_end=$(python3 "$repo/core/scripts/nixstrap.lib-part.py" boot-end 1MiB 1GiB) || die "boot-end 계산 실패"
    [[ $(vmx "$GOLDEN_INST" sh -c 'lsblk -dno SIZE,TYPE /dev/sda') == *disk* ]] || die "/dev/sda 가 없습니다"
    vmx "$GOLDEN_INST" sh -c "cat > /root/nixstrap-params.env" <<PARAMS_EOF
NIXOS_REPO=donghans/nixos
HOST=sbox-nixos
_HOST_IS_NEW=true
_HOST_TYPE=
_HOST_PRESET_FROM_REPO=
_PRESET=workstation
_STATE_VERSION=
_HOST_USERNAME=$VM_USER
_PART_MODE=2
_NEW_PARTITIONS=true
BOOT_PART=/dev/sda1
ROOT_PART=/dev/sda2
FORMAT_BOOT=y
FORMAT_ROOT=y
_DISK=/dev/sda
_WIPE=true
_PART_START=1MiB
_PART_END=100%
_BOOT_SIZE=1GiB
_BOOT_END=$boot_end
_NEW_BOOT_NUM=1
_NEW_ROOT_NUM=2
_SSH_ACCESS_MODE=
_SSH_KEY_FILE=
_SSH_KEY_GENERATED=false
_LUKS=false
_IS_LAPTOP=false
_REFIND=false
PARAMS_EOF
    audit info rebuild-golden "$GOLDEN_INST" "ISO 부팅·params 주입 완료, nixstrap 시작($((SECONDS - t0))초)"
    # 비밀번호: 무작위로 만들어 표준입력으로만 넘긴다(저장·출력 안 함). VM 안 Claude 가 sudo 를 못 쓰게 하는 방침과 같다 —
    # 관리가 필요하면 호스트에서 incus exec(root) 로 하거나 passwd 로 새로 정한다.
    local log
    log=${SBOX_INSTALL_LOG:-$HOME/.local/state/sbox/rebuild-golden-$(date +%y%m%d-%H%M%S).log}
    mkdir -p "$(dirname "$log")"
    say "nixstrap 자동 설치 시작(로그 $log)"
    # 설치 중에도 호스트 nix-serve 캐시를 쓴다(공개 캐시에 없는 로컬 빌드물을 재빌드하지 않게). 라이브 환경의 root 는 신뢰 사용자라 NIX_CONFIG 가 먹는다.
    local nixcfg
    nixcfg=$(printf 'extra-substituters = %s\nextra-trusted-public-keys = %s' "$CACHE_URL" "$(cache_key)")
    # 에이전트는 DHCP 보다 먼저 응답하므로 네트워크가 올라올 때까지 최대 60초 기다린다
    local _n up=0
    for _n in $(seq 1 30); do
        vmx "$GOLDEN_INST" curl -sf --max-time 3 "$CACHE_URL/nix-cache-info" >/dev/null 2>&1 && { up=1; break; }
        sleep 2
    done
    ((up)) || die "라이브 환경에서 캐시($CACHE_URL)에 닿지 않습니다(60초 대기)"
    if ! head -c 18 /dev/urandom | base64 | vmx_env "$GOLDEN_INST" NIXSTRAP_AUTO=1 TERM=dumb "NIX_CONFIG=$nixcfg" -- nixstrap-wrapped >"$log" 2>&1; then
        die "nixstrap 설치 실패 — 로그: $log (VM $GOLDEN_INST 는 남겨 둡니다)"
    fi
    say "설치 끝($((SECONDS - t0))초) — 재부팅"
    incus stop "$GOLDEN_INST"
    incus config device remove "$GOLDEN_INST" iso
    incus config set "$GOLDEN_INST" raw.qemu="-cpu host,-vmx"
    incus start "$GOLDEN_INST"
    wait_agent "$GOLDEN_INST"
    # 홈이 설치 중에 적용되지 않았으면 여기서 적용
    if ! vmu "$GOLDEN_INST" test -x "$VM_HOME/.nix-profile/bin/claude"; then
        say "설치 중 홈 적용이 안 됐음 — 재부팅 뒤 nixup home"
        home_apply "$GOLDEN_INST"
    fi
    vmu "$GOLDEN_INST" test -x "$VM_HOME/.nix-profile/bin/claude" || die "골든에 claude 가 없습니다"
    vmx "$GOLDEN_INST" sh -c "rm -f $VM_HOME/.nixstrap-first-run; sync"
    incus stop "$GOLDEN_INST"
    incus snapshot create "$GOLDEN_INST" "$GOLDEN_SNAP"
    audit info rebuild-golden "$GOLDEN_INST" "처음부터 재생성 완료($((SECONDS - t0))초)"
    say "완료: $GOLDEN_INST@$GOLDEN_SNAP ($((SECONDS - t0))초)"
}

cache_key() { # 호스트 nix-serve 의 공개키(읽을 수 있으면 호스트 파일, 아니면 기본값)
    local key=$CACHE_KEY_DEFAULT
    if [[ -r $CACHE_PUB_FILE ]]; then
        key=$(<"$CACHE_PUB_FILE")
        [[ $key == "$CACHE_KEY_DEFAULT" ]] || say "주의: 호스트 공개키가 기본값과 다릅니다 — 호스트 키($CACHE_PUB_FILE)를 씁니다"
    fi
    printf '%s' "$key"
}

cmd_cache() {
    local name=$1 key
    check_name "$name"
    require_vm
    key=$(cache_key)
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
        die "캐시 등록은 했으나 VM 에서 $CACHE_URL 에 닿지 않습니다(호스트 nix-serve·sbox-guard 확인)"
    fi
}

cmd_home() { check_name "${1:-}"; require_vm; home_apply "$1"; }

home_apply() { # 이름 규칙 검사 없이 홈 적용(rebuild-golden 이 골든 이름으로도 부른다)
    local name=$1
    resolve_ids "$name"
    # nixup 은 ~/.cache/nixos/build/hardware.nix 가 없으면 sudo 로 만들려 한다 — 터미널이 없어 실패하므로 root 가 미리 만들어 둔다.
    vmx "$name" sh -c "
        set -e
        d=$VM_HOME/.cache/nixos/build; mkdir -p \$d
        [ -s \$d/hardware.nix ] || nixos-generate-config --no-filesystems --show-hardware-config > \$d/hardware.nix
        chown -R $VM_UID:$VM_GID $VM_HOME/.cache" || { audit critical home "$name" "hardware.nix 준비 실패"; return 0; }
    # 호스트 nix-serve 캐시를 이 호출에만 적용한다(NIX_CONFIG — sbox 사용자는 wheel 이라 신뢰 사용자). 이미지·nix.conf 는 건드리지 않는다.
    local NIX_CFG
    NIX_CFG=$(printf 'extra-substituters = %s\nextra-trusted-public-keys = %s' "$CACHE_URL" "$(cache_key)")
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
    resolve_ids "$name"
    # 값은 환경변수 → 표준입력으로만 흐른다(명령줄에 없음). 파일은 VM tmpfs, 0600, sbox 소유.
    # shellcheck disable=SC2016  # $VM_CLAUDE_TOKEN·$1.. 는 donghans secret run 이 띄운 셸이 펼친다(명령줄에 값이 없게)
    donghans secret run --env VM_CLAUDE_TOKEN -- sh -c '
        printf %s "$VM_CLAUDE_TOKEN" | incus exec "$1" --env PATH="$2" -- sh -c "
            set -e; umask 077; mkdir -p /run/sbox-claude; cat > $3
            chown -R $4:$5 /run/sbox-claude; chmod 700 /run/sbox-claude"
    ' sh "$name" "$EXEC_PATH" "$TOKEN_PATH" "$VM_UID" "$VM_GID"
    local bytes
    bytes=$(vmx "$name" sh -c "wc -c < $TOKEN_PATH")
    [[ ${bytes//[[:space:]]/} -gt 20 ]] || die "토큰 파일이 비어 있거나 너무 짧습니다(${bytes}바이트)"
    audit info token "$name" "VM_CLAUDE_TOKEN 주입(tmpfs, ${bytes//[[:space:]]/}바이트)"
    say "토큰 주입 완료(tmpfs $TOKEN_PATH, ${bytes//[[:space:]]/}바이트, 값은 출력하지 않음)"
}

wait_ct() { # wait_ct NAME — 컨테이너가 exec 에 응답하고 기본 경로(네트워크)가 생길 때까지(최대 약 2분)
    local n=$1 ok=0
    for _ in $(seq 1 60); do
        incus exec "$n" --env "PATH=$CT_PATH" -- true >/dev/null 2>&1 </dev/null && { ok=1; break; }
        sleep 1
    done
    ((ok)) || die "$n 이 60초 안에 응답하지 않았습니다"
    for _ in $(seq 1 60); do
        incus exec "$n" --env "PATH=$CT_PATH" -- sh -c 'ip route 2>/dev/null | grep -q "^default"' >/dev/null 2>&1 </dev/null && return 0
        sleep 1
    done
    die "$n 의 네트워크(기본 경로)가 60초 안에 올라오지 않았습니다"
}

# 컨테이너 종류 v1 (plan dev-sandbox-pilot §23 S1~S3). 정책: 비특권만, 비 root 사용자 sbox 에 sudo 없음, 종료된 릴리스는 --legacy 필요.
create_ct() { # create_ct NAME FLAVOR RELEASE LEGACY NESTING CPU MEM TOKEN
    local name=$1 flavor=$2 release=$3 legacy=$4 nesting=$5 cpu=$6 mem=$7 token=$8
    [[ -n $flavor ]] || die "ct 종류는 --flavor 가 필요합니다(debian|ubuntu)"
    case $flavor in
        debian|ubuntu) ;;
        arch|gentoo) die "$flavor 컨테이너는 아직 구현 전입니다(체크리스트 S7·S8)" ;;
        *) die "알 수 없는 flavor: $flavor (debian|ubuntu)" ;;
    esac
    local info key ver status eol image note
    info=$(python3 "$SBOX_DIR/release.py" resolve "$flavor" "$release") || die "릴리스 조회 실패"
    IFS=$'\x1f' read -r key ver status eol image note <<<"$info"   # 탭이 아니라 \x1f — 빈 종료일이 합쳐지면 필드가 밀린다(2026-11-22 실제로 겪음)
    export AUDIT_FLAVOR=$flavor AUDIT_RELEASE=$key AUDIT_EOL=false
    say "릴리스: $flavor $ver($key) 상태 $status${eol:+, 종료일 $eol}${note:+ — $note}"
    if [[ $status == eol ]]; then
        ((legacy)) || die "$flavor $ver($key)는 지원이 끝난 릴리스입니다 — 레거시·마이그레이션 목적이면 --legacy 를 주세요"
        AUDIT_EOL=true
        say "경고: $flavor $ver($key)는 지원 종료 릴리스입니다(보안 패치 없음). 네트워크는 sbox-guard 안에서만 나갑니다."
    fi
    if [[ $image == build:* ]]; then
        die "$flavor $ver($key)는 incus 이미지가 없어 직접 빌드해야 합니다(${image#build:}) — 방법은 plan dev-sandbox-pilot §22-3, 구현은 체크리스트 S9"
    fi
    local vclean=${ver//./}
    local want="sbox-ct-$flavor$vclean-"
    [[ -n $name ]] || name="$want$(date +%y%m%d-%H%M)"
    [[ $name == "$want"* ]] || die "이름은 $want 로 시작해야 합니다(받은 이름: $name) — 규칙: sbox-ct-<flavor><버전(점 제거)>-<이름>"
    check_name "$name"
    incus info "$name" >/dev/null 2>&1 && die "$name 은 이미 있습니다"
    incus network show "$NETWORK" >/dev/null 2>&1 || die "브리지 $NETWORK 가 없습니다"

    say "생성: $name ← images:$image (비특권 컨테이너, cpu $cpu·메모리 $mem$( ((nesting)) && echo ', nesting' ))"
    local -a opts=(-n "$NETWORK" -c "limits.cpu=$cpu" -c "limits.memory=$mem")
    ((nesting)) && opts+=(-c security.nesting=true)
    local _try _err
    for _try in 1 2 3; do
        if _err=$(timeout 180 incus init "images:$image" "$name" "${opts[@]}" 2>&1 </dev/null); then break; fi
        say "incus init 실패($_try/3): ${_err##*$'\n'}"
        incus delete -f "$name" >/dev/null 2>&1 </dev/null || true
        sleep 10
        [[ $_try == 3 ]] && die "incus init 3회 실패($name): ${_err##*$'\n'}"
    done
    # 정책 검사: 특권 컨테이너·호스트 장치 직결이 아닌지(프로필·인스턴스 합산 설정에서 확인). 어긋나면 만든 것을 지우고 거부.
    if incus config show "$name" --expanded 2>/dev/null </dev/null | grep -qE '^\s*security\.privileged:\s*"?true'; then
        incus delete -f "$name" >/dev/null 2>&1 </dev/null || true
        die "정책 위반: 특권 컨테이너가 됐습니다 — 거부하고 삭제했습니다"
    fi
    incus start "$name" </dev/null
    wait_ct "$name"
    # 비 root 사용자 sbox: sudo 그룹에 넣지 않는다(Claude 에게 root 를 주지 않는 방침 — plan §15)
    incus exec "$name" --env "PATH=$CT_PATH" -- sh -c "id $VM_USER >/dev/null 2>&1 || useradd -m -s /bin/bash $VM_USER" </dev/null \
        || die "사용자 $VM_USER 생성 실패"
    ((token)) && cmd_token "$name"

    local ip
    ip=$(incus list "$name" -f json </dev/null | python3 -c 'import sys,json
d=json.load(sys.stdin)[0]["state"]["network"]
print(" ".join(a["address"] for a in d.get("eth0",{}).get("addresses",[]) if a["family"]=="inet"))')
    audit info create "$name" "컨테이너 images:$image, ${flavor} ${ver}(${key}) ${status}, $ip, 비특권, cpu $cpu·메모리 $mem"
    say "완료: $name  ($ip) — 사용자 $VM_USER(sudo 없음), 토큰은 $TOKEN_PATH(tmpfs)"
    say "알림: Node 등은 'sbox.sh tools $name --from-repo <저장소>' 로 읽기 전용 도구 층을 붙입니다(S5 v1: node 만)"
}

cmd_create() {
    local name="" cache=1 token=1 home=1 kind="" flavor="" release="" legacy=0 nesting=0 cpu=2 mem=2GiB
    while (($#)); do
        case $1 in
            --no-cache) cache=0 ;;
            --no-token) token=0 ;;
            --no-home) home=0 ;;
            --kind) shift; kind=${1:-} ;;
            --flavor) shift; flavor=${1:-} ;;
            --release) shift; release=${1:-} ;;
            --legacy) legacy=1 ;;
            --nesting) nesting=1 ;;
            --cpu) shift; cpu=${1:-} ;;
            --memory) shift; mem=${1:-} ;;
            -*) die "알 수 없는 옵션: $1" ;;
            *) name=$1 ;;
        esac
        shift
    done
    # 종류는 필수·기본값 없음: 빠뜨리면 실패한다(VM 용 보안 가정이 컨테이너로 번지지 않게 — plan §15 조건 ①)
    case "$kind" in
        vm) ;;
        ct) create_ct "$name" "$flavor" "$release" "$legacy" "$nesting" "$cpu" "$mem" "$token"; return ;;
        "") die "--kind vm|ct 가 필요합니다(기본값 없음)" ;;
        *) die "알 수 없는 종류: $kind (vm|ct)" ;;
    esac
    [[ -z $flavor || $flavor == nixos ]] || die "vm 종류는 nixos 만 구현돼 있습니다(받은 flavor: $flavor)"
    [[ -n $name ]] || name="sbox-vm-$(date +%y%m%d-%H%M)"
    check_name "$name"
    incus info "$GOLDEN_INST" >/dev/null 2>&1 || die "골든 $GOLDEN_INST 가 없습니다 — 먼저 'sbox.sh golden'"
    incus info "$name" >/dev/null 2>&1 && die "$name 은 이미 있습니다"
    incus network show "$NETWORK" >/dev/null 2>&1 || die "브리지 $NETWORK 가 없습니다"

    say "생성: $name ← $GOLDEN_INST@$GOLDEN_SNAP (스냅샷 복제, vmx 마스킹 켬 = 중첩 가상화 기본 꺼짐)"
    # incus 클라이언트가 수십 분 멈춘 적이 있다(2026-11-22 네 번, 원인 미확인 — 새 이름으로도 재현) —
    # 시간 제한을 두고 실패하면 반쯤 만들어진 것을 지운 뒤 재시도한다.
    local _try _err
    for _try in 1 2 3; do
        if _err=$(timeout 180 incus copy "$GOLDEN_INST/$GOLDEN_SNAP" "$name" 2>&1 </dev/null); then break; fi
        say "incus copy 실패($_try/3): ${_err##*$'\n'}"
        incus delete -f "$name" >/dev/null 2>&1 || true
        sleep 10
        [[ $_try == 3 ]] && die "incus copy 3회 실패($name): ${_err##*$'\n'}"
    done
    incus config set "$name" raw.qemu="-cpu host,-vmx"
    incus config device get "$name" eth0 network 2>/dev/null | grep -qx "$NETWORK" || die "$name 의 eth0 가 $NETWORK 에 붙어 있지 않습니다"
    incus start "$name"
    wait_agent "$name"
    # 골든은 같은 호스트명·머신 ID 를 물려받는다 — 같은 시기에 여러 대를 띄워도 DHCP 는 MAC 으로 구분되므로 두고 간다.

    ((home)) && home_apply "$name"
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
    local name="" repo_path=""
    while (($#)); do
        case $1 in
            --repo) shift; repo_path=${1:-} ;;
            -*) die "알 수 없는 옵션: $1" ;;
            *) name=$1 ;;
        esac
        shift
    done
    check_name "$name"
    if [[ -z $repo_path ]]; then
        [[ $NAME_KIND == vm ]] || die "ct 종류는 --repo <컨테이너 안 저장소 경로> 가 필요합니다(예: /home/$VM_USER/proj)"
        repo_path=$VM_REPO
    fi
    [[ $(incus list "$name" -f csv -c s) == RUNNING ]] || die "$name 이 실행 중이 아니라 번들을 꺼낼 수 없습니다"
    vmu "$name" test -d "$repo_path/.git" || die "$repo_path 에 저장소가 없습니다"
    mkdir -p "$BUNDLE_DIR"
    local out
    out="$BUNDLE_DIR/$name-$(date +%y%m%d-%H%M%S).bundle"
    # 미커밋 변경은 번들에 안 들어간다 — 있으면 알린다(destroy 는 이것으로 거부)
    local dirty
    dirty=$(vmu "$name" git -C "$repo_path" status --porcelain 2>/dev/null | grep -Ev "$DIRTY_IGNORE" || true)
    if [[ -n $dirty ]]; then
        say "미커밋 변경 $(wc -l <<<"$dirty")건 — 번들에 들어가지 않습니다:"
        head -20 <<<"$dirty" | while IFS= read -r l; do printf '    %s\n' "$l"; done >&2
        SBOX_DIRTY=1
    fi
    vmu "$name" git -C "$repo_path" bundle create - --all >"$out" 2>/dev/null || { rm -f "$out"; die "번들 생성 실패"; }
    [[ -s $out ]] || { rm -f "$out"; die "번들이 비었습니다"; }
    (cd "$(dirname "$(readlink -f "$0")")/../.." && git bundle verify "$out" >/dev/null 2>&1) \
        || { say "경고: 호스트 저장소에서 verify 실패 — 번들은 남깁니다: $out"; }
    audit info bundle "$name" "$out"
    say "번들 저장: $out ($(du -h "$out" | cut -f1))"
    BUNDLE_OUT=$out
}

cmd_import() {
    local bundle=${1:-}
    [[ -r $bundle ]] || die "읽을 수 있는 번들 파일이 필요합니다: ${bundle:-(없음)}"
    local repo base vm
    repo=$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)
    base=$(basename "$bundle" .bundle)
    vm=${base%-[0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9]}
    [[ $vm =~ ^[a-z0-9][a-z0-9-]*$ ]] || die "번들 이름에서 VM 이름을 알 수 없습니다($base)"
    git -C "$repo" bundle verify "$bundle" >/dev/null 2>&1 || die "번들 검증 실패 — 필요한 선행 커밋이 호스트 저장소에 없거나 파일이 깨졌습니다"
    # 별도 ref 로만 받는다: 호스트의 브랜치·작업 트리는 건드리지 않는다. VM 안 내용은 신뢰하지 않으므로 사람이 보고 cherry-pick/병합한다.
    git -C "$repo" fetch --quiet "$bundle" "refs/heads/*:refs/sbox/$vm/*" || die "fetch 실패"
    say "가져옴: refs/sbox/$vm/*  (호스트 작업 트리·브랜치는 그대로)"
    local ref
    while IFS= read -r ref; do
        say "── $ref : 호스트 HEAD 에 없는 커밋"
        git -C "$repo" log --oneline --no-decorate "HEAD..$ref" | head -30 >&2
    done < <(git -C "$repo" for-each-ref --format='%(refname)' "refs/sbox/$vm/")
    say "검토: git log HEAD..refs/sbox/$vm/<브랜치> · 반영: git cherry-pick / git merge --no-ff (사람이 확인한 뒤)"
    audit info import "$vm" "$bundle → refs/sbox/$vm/*"
}

cmd_destroy() {
    local name="" force=0 discard=0 repo_path="" nobundle=0
    while (($#)); do
        case $1 in
            --repo) shift; repo_path=${1:-} ;;
            --no-bundle) nobundle=1 ;;
            --force) force=1 ;;
            --discard-dirty) discard=1 ;;
            -*) die "알 수 없는 옵션: $1" ;;
            *) name=$1 ;;
        esac
        shift
    done
    check_name "$name"
    incus info "$name" >/dev/null 2>&1 || die "$name 이 없습니다"
    SBOX_DIRTY=0
    if ((force)); then
        say "--force: 번들 없이 지웁니다"
    elif ((nobundle)); then
        say "--no-bundle: 번들 없이 지웁니다(저장소가 없거나 필요 없다고 확인한 경우)"
        audit info destroy-nobundle "$name" "번들 없이 삭제 요청"
    else
        if [[ $NAME_KIND == ct && -z $repo_path ]]; then
            die "ct 종류는 --repo <컨테이너 안 저장소 경로>(번들을 먼저 꺼냄) 또는 --no-bundle 이 필요합니다"
        fi
        if [[ -n $repo_path ]]; then cmd_bundle "$name" --repo "$repo_path"; else cmd_bundle "$name"; fi
        if ((SBOX_DIRTY)) && ((!discard)); then
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

# 도구 층 v1 (plan dev-sandbox-pilot §29, S5·S34): 호스트가 공식 파일을 받아 sha256 검증 → 컨테이너에 읽기 전용으로만 마운트.
# 사용: tools NAME [--from-repo DIR | --manifest FILE] [--update] [TOOL=SPEC ...]   (v1: node 만)
#  --from-repo/--manifest 는 ~/.config/sbox/manifests/<프로젝트>.toml 을 만들거나 갱신하고 **정확한 버전을 [resolved] 에 고정**한다
#  (22 같은 느슨한 스펙이 나중에 다른 패치로 조용히 바뀌지 않음). 다시 해석하려면 --update. TOOL=SPEC 은 매니페스트에 [override] 로 기록된다.
cmd_tools() {
    local name=${1:-}; shift || true
    [[ -n $name ]] || die "사용법: sbox.sh tools NAME [--from-repo DIR | --manifest FILE] [--update] [node=22 ...]"
    check_name "$name"
    [[ $NAME_KIND == ct ]] || die "도구 층 v1 은 컨테이너(ct)만 지원합니다"
    incus info "$name" >/dev/null 2>&1 </dev/null || die "$name 이 없습니다"
    local -a pargs=() inline=()
    local a
    while (($#)); do
        a=$1; shift
        case $a in
            --from-repo) pargs+=(--repo "${1:?}"); shift ;;
            --manifest) pargs+=(--manifest "${1:?}"); shift ;;
            --update) pargs+=(--update) ;;
            *=*) inline+=("$a"); pargs+=(--tool "$a") ;;
            *) die "알 수 없는 인자: $a" ;;
        esac
    done
    local plan
    if printf '%s\n' "${pargs[@]}" | grep -qE '^--(repo|manifest)$'; then
        plan=$(python3 "$SBOX_DIR/tools.py" plan "${pargs[@]}") || die "매니페스트 계획 실패"
    else
        ((${#inline[@]})) || die "설치할 도구가 없습니다(--from-repo·--manifest 또는 TOOL=SPEC 필요)"
        local -a t=(); for a in "${inline[@]}"; do t+=(--tool "$a"); done
        # 매니페스트 없이 일회성 — 임시 이름의 매니페스트를 만들지 않으려 resolve 만 쓴다
        plan='{"manifest":"","tools":{'
        local first=1 k spec ver
        for a in "${inline[@]}"; do
            k=${a%%=*}; spec=${a#*=}
            [[ $k == node ]] || die "도구 층 v1 은 node 만 지원합니다(받은 도구: $k)"
            ver=$(python3 "$SBOX_DIR/tools.py" resolve "$k" "$spec") || die "$k $spec 버전 해석 실패"
            ((first)) || plan+=","; first=0
            plan+="\"$k\":{\"spec\":\"$spec\",\"version\":\"$ver\",\"source\":\"인자\",\"how\":\"일회성\"}"
        done
        plan+='}}'
    fi
    local k spec ver src how dir dev
    while IFS=$'\x1f' read -r k spec ver src how; do
        [[ $k == node ]] || die "도구 층 v1 은 node 만 지원합니다(받은 도구: $k)"
        say "도구: $k $spec → $ver ($src, $how)"
        dir=$(python3 "$SBOX_DIR/tools.py" fetch "$k" "$ver") || die "$k $ver 받기·검증 실패"
        dev="tools-$k-${ver//./_}"
        if ! incus config device show "$name" </dev/null | grep -q "^$dev:"; then
            incus config device add "$name" "$dev" disk source="$dir" path="/opt/tools/$k/$ver" readonly=true </dev/null \
                || die "읽기 전용 장치 추가 실패($dev)"
        fi
        incus exec "$name" --env "PATH=$CT_PATH" -- sh -c "for b in node npm npx corepack; do ln -sfn /opt/tools/$k/$ver/bin/\$b /usr/local/bin/\$b; done" </dev/null \
            || die "/usr/local/bin 연결 실패"
        audit info tools "$name" "$k $ver 읽기 전용 마운트(스펙 $spec, $src, $how)"
        say "완료: $k $ver — /opt/tools/$k/$ver (읽기 전용), /usr/local/bin 에 연결"
    done < <(printf '%s' "$plan" | python3 -c 'import sys,json
d=json.load(sys.stdin)
if d["manifest"]: print("매니페스트:", d["manifest"], file=sys.stderr)
for k,v in d["tools"].items(): print("\x1f".join([k,v["spec"],v["version"],v["source"],v["how"]]))')
}

cmd_list() { incus list '^sbox-' -c ns4 -f compact; }

case "${1:-}" in
    create) shift; cmd_create "$@" ;;
    bundle) shift; cmd_bundle "$@" ;;
    releases) shift; python3 "$SBOX_DIR/release.py" list "${1:-}" ;;
    destroy) shift; cmd_destroy "$@" ;;
    import) shift; cmd_import "${1:-}" ;;
    golden) shift; cmd_golden "$@" ;;
    rebuild-golden) shift; cmd_rebuild_golden "$@" ;;
    iso) shift; cmd_iso "$@" ;;
    cache) shift; cmd_cache "${1:-}" ;;
    token) shift; cmd_token "${1:-}" ;;
    home) shift; cmd_home "${1:-}" ;;
    tools) shift; cmd_tools "$@" ;;
    list) cmd_list ;;
    *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2 ;;
esac
