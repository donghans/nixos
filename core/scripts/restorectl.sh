#!/usr/bin/env bash
# restorectl.sh — 재설치 뒤 백업 번들(beelink) 복원 도우미 (plan nixstrap-luks §4-2 P8)
#
# 사용 (저장소에서):  bash core/scripts/restorectl.sh <명령> [옵션]
#   key      새 노트북의 ssh 키를 만들고 beelink 에 등록한다(비밀번호는 ssh 가 직접 묻는다 — 별도 터미널에서 실행하고
#            비밀번호를 대화·로그에 남기지 말 것). beelink 는 PasswordAuthentication=no 이지만 keyboard-interactive 로 받는다.
#   fetch    번들(.tar.zst·MANIFEST·SHA256SUMS)을 임시 폴더로 가져온다(scp; --from-dir 이면 로컬/USB 폴더에서 복사).
#   verify   SHA256SUMS 로 무결성 확인(이 파일은 `sha256sum -c` 형식이 아니라서 순서를 바꿔 검사한다).
#   extract  임시 폴더 안에 푼다(홈·시스템은 건드리지 않는다). 목록 확인용으로도 쓴다.
#   pick     푼 것에서 필요한 항목만 ~ 로 복사한다(기존 파일은 덮어쓰지 않음 — 새로 만든 키·home-manager 파일 보호).
#   clean    임시 폴더(평문 비밀 포함)를 지운다. 복원이 끝나면 반드시 실행.
# 옵션: --host H(기본 beelink-ser7-co) --src DIR(beelink 의 번들 폴더 이름) --stage DIR --from-dir DIR --yes
set -euo pipefail

HOST="beelink-ser7-co"
SRC="backup-msi-summit-me-20261110"
STAGE="${RESTORECTL_STAGE:-$HOME/.cache/restorectl}"
FROM_DIR=""
YES=false
# pick 의 기본 항목(~ 기준). ~/.claude 의 지침·스킬은 home-manager 가 만들므로 settings.json 만 둔다.
# 기록(.claude/projects 등)·ctx 는 beelink 정본이라 기본에서 뺐다. 더 필요하면 `pick 경로…` 로 직접 지정한다.
DEFAULT_PICK=(.ssh .gnupg .local/share/nix-secrets .local/share/keyrings .config/Bitwarden .claude/settings.json)

die() { printf 'restorectl: %s\n' "$*" >&2; exit 1; }
info() { printf 'restorectl: %s\n' "$*"; }

usage() { sed -n '2,15p' "$0" | sed 's/^# \{0,1\}//'; }

[ $# -ge 1 ] || { usage; exit 1; }
case "$1" in -h|--help) usage; exit 0 ;; esac
CMD=$1; shift
EXTRA=()
while [ $# -gt 0 ]; do
    case "$1" in
        --host) HOST=${2:?--host 값 필요}; shift 2 ;;
        --src) SRC=${2:?--src 값 필요}; shift 2 ;;
        --stage) STAGE=${2:?--stage 값 필요}; shift 2 ;;
        --from-dir) FROM_DIR=${2:?--from-dir 값 필요}; shift 2 ;;
        --yes) YES=true; shift ;;
        -h|--help) usage; exit 0 ;;
        --) shift; EXTRA+=("$@"); break ;;
        -*) die "알 수 없는 옵션: $1" ;;
        *) EXTRA+=("$1"); shift ;;
    esac
done
BUNDLE="$STAGE/bundle"
OUT="$STAGE/extracted"

_stage_init() { mkdir -p "$STAGE" && chmod 700 "$STAGE"; }

cmd_key() {
    local key="$HOME/.ssh/id_ed25519"
    mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
    if [ ! -f "$key" ]; then
        info "새 ssh 키를 만듭니다($key) — 암호(passphrase)는 직접 정하세요."
        ssh-keygen -t ed25519 -f "$key" -C "$(whoami)@$(hostname)"
    else
        info "기존 키 사용: $key"
    fi
    info "$HOST 에 공개키를 등록합니다. 비밀번호를 물으면 직접 입력하세요(이 화면을 대화에 붙여 넣지 마세요)."
    ssh-copy-id -i "$key.pub" "$HOST"
    if ssh -o BatchMode=yes -o PasswordAuthentication=no "$HOST" true; then
        info "키 접속 확인됨"
    else
        die "등록 뒤에도 키 접속이 안 됩니다(beelink 의 ~/.ssh 권한·홈 디렉터리 권한을 확인하세요)."
    fi
}

cmd_fetch() {
    _stage_init; mkdir -p "$BUNDLE" && chmod 700 "$BUNDLE"
    local f
    for f in linux-home.tar.zst windows.tar.zst system-root.tar.zst MANIFEST-linux.txt MANIFEST-windows.txt SHA256SUMS.txt; do
        if [ -n "$FROM_DIR" ]; then
            [ -f "$FROM_DIR/$f" ] || die "없음: $FROM_DIR/$f"
            cp -- "$FROM_DIR/$f" "$BUNDLE/$f"
        else
            scp -p -- "$HOST:$SRC/$f" "$BUNDLE/$f" || die "가져오기 실패: $f"
        fi
        info "가져옴: $f"
    done
    cmd_verify
}

cmd_verify() {
    [ -f "$BUNDLE/SHA256SUMS.txt" ] || die "$BUNDLE/SHA256SUMS.txt 가 없습니다 — 먼저 fetch."
    local lines
    # SHA256SUMS.txt 는 `<파일명> <해시>`(주석 줄 포함)이라 sha256sum -c 가 못 읽는다 → `<해시>  <파일명>` 으로 바꿔 검사
    lines=$(awk '!/^#/ && NF==2 {print $2"  "$1}' "$BUNDLE/SHA256SUMS.txt")
    [ -n "$lines" ] || die "SHA256SUMS.txt 에서 검사할 줄을 찾지 못했습니다."
    [ "$(printf '%s\n' "$lines" | wc -l)" -ge 3 ] || die "SHA256SUMS.txt 의 항목이 3개 미만입니다(번들 3개를 모두 검사해야 함)."
    (cd "$BUNDLE" && printf '%s\n' "$lines" | sha256sum -c -) || die "무결성 검사 실패 — 풀지 마세요."
    info "무결성 확인됨"
}

cmd_extract() {
    command -v zstd >/dev/null 2>&1 || die "zstd 가 없습니다: nix shell nixpkgs#zstd -c bash $0 extract …"
    [ -f "$BUNDLE/linux-home.tar.zst" ] || die "번들이 없습니다 — 먼저 fetch."
    cmd_verify
    local pair name dir
    for pair in linux-home:home windows:windows system-root:system-root; do
        name=${pair%%:*}; dir=${pair##*:}
        mkdir -p "$OUT/$dir" && chmod 700 "$OUT/$dir"
        tar --zstd -xf "$BUNDLE/$name.tar.zst" -C "$OUT/$dir" --no-same-owner
        info "풀었음: $OUT/$dir ($(find "$OUT/$dir" -type f | wc -l)개 파일)"
    done
    info "홈은 건드리지 않았습니다. 필요한 것만 'pick' 으로 복사하세요."
}

cmd_pick() {
    [ -d "$OUT/home" ] || die "푼 폴더가 없습니다 — 먼저 extract."
    local -a items=("${EXTRA[@]}")
    [ ${#items[@]} -gt 0 ] || items=("${DEFAULT_PICK[@]}")
    local it src dst ans
    for it in "${items[@]}"; do
        it=${it#./}; it=${it#"$HOME"/}
        case "$it" in /*|*..*) die "상대 경로(~ 기준)만 허용합니다: $it" ;; esac
        src="$OUT/home/$it"; dst="$HOME/$it"
        [ -e "$src" ] || { info "건너뜀(번들에 없음): $it"; continue; }
        if ! $YES; then
            read -rp "복사할까요? $it  (덮어쓰지 않음) [y/N]: " ans || ans=n
            [[ "$ans" =~ ^[Yy]$ ]] || { info "건너뜀: $it"; continue; }
        fi
        # 디렉터리는 안쪽 내용만 합친다(`cp -a 디렉터리 기존디렉터리` 는 한 겹 더 들어가 버린다). -n: 기존 파일은 덮어쓰지 않음(건너뛴 파일이 있으면 종료 코드가 0 이 아닐 수 있어 무시).
        if [ -d "$src" ]; then
            mkdir -p "$dst"
            cp -a -n -- "$src/." "$dst/" || true
        else
            mkdir -p "$(dirname "$dst")"
            cp -a -n -- "$src" "$dst" || true
        fi
        info "복사: $it"
    done
    [ -d "$HOME/.ssh" ] && chmod 700 "$HOME/.ssh"
    [ -d "$HOME/.gnupg" ] && chmod 700 "$HOME/.gnupg"
    info "기존 파일은 그대로 두었습니다(같은 이름은 옛 것이 복사되지 않음). 끝나면 'clean' 으로 임시 폴더를 지우세요."
}

cmd_clean() {
    [ -d "$STAGE" ] || { info "지울 것이 없습니다: $STAGE"; return 0; }
    rm -rf -- "$STAGE" && info "삭제함: $STAGE"
}

case "$CMD" in
    key) cmd_key ;;
    fetch) cmd_fetch ;;
    verify) cmd_verify ;;
    extract) cmd_extract ;;
    pick) cmd_pick ;;
    clean) cmd_clean ;;
    *) usage; die "알 수 없는 명령: $CMD" ;;
esac
