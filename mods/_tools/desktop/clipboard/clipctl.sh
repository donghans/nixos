#!/usr/bin/env bash
# clipctl — cliphist 클립보드 이력 관리 CLI
# (Nix 가 @...@ 자리표시자를 실제 경로로 치환한다 — mods/gui/base/clipboard-menu.nix)
set -u
export PATH="@path@:$PATH"

CLIPHIST="@cliphist@"
CLIPMETA="${CLIPMETA_CMD:-@clipmeta@}"   # 부가 정보(시각·앱·횟수) 사이드카 도구
DB="${CLIPHIST_DB:-${XDG_CACHE_HOME:-$HOME/.cache}/cliphist/db}"
SERVICE="${CLIPCTL_SERVICE:-cliphist.service}"
PREVIEW=100

CH() { "$CLIPHIST" -db-path "$DB" "$@"; }
human() { numfmt --to=iec --suffix=B "${1:-0}"; }
die() { echo "clipctl: $*" >&2; exit 1; }

usage() {
  cat <<USAGE
clipctl — 클립보드 이력(cliphist) 관리

사용법: clipctl <명령> [인자]

  stats                          개수, 내용 총 크기, DB 파일 크기, 큰 항목
  find <키워드> [옵션]           내용(전문)에 키워드가 있는 항목 목록
  delete <키워드> [옵션]         키워드가 있는 항목 삭제 (확인 후)
  big [KB]                       KB 이상 항목 목록 (기본 10)
  delete-big <KB> [-y]           KB 이상 항목 삭제 (확인 후)
  compact                        DB 파일 최적화 (백업 후 재구성, 이력 번호는 새로 매겨짐)
  wipe [-y]                      이력 전체 삭제

옵션:
  -E   키워드를 정규식으로 해석 (기본: 일반 문자열)
  -s   대소문자 구분 (기본: 구분 안 함)
  -y   확인 없이 바로 실행
  -n   삭제하지 않고 대상만 표시 (delete, delete-big)
  --tsv  기계가 읽기 쉬운 형식 (id<TAB>바이트<TAB>미리보기)

환경변수: CLIPHIST_DB (DB 경로, 기본 ~/.cache/cliphist/db)
USAGE
}

# scan [패턴]  →  "id<TAB>크기<TAB>일치(0/1)<TAB>미리보기" (전문 기준으로 크기/일치 계산)
scan() {
  local pattern="${1:-}" list id preview size m tmp
  list=$(CH -preview-width "$PREVIEW" list) || return 1
  tmp=$(mktemp)
  while IFS=$'\t' read -r id preview; do
    [ -z "$id" ] && continue
    CH decode "$id" >"$tmp" 2>/dev/null
    size=$(wc -c <"$tmp")
    if [ -n "$pattern" ]; then
      if grep -a -q "${GREP_OPTS[@]}" -- "$pattern" "$tmp"; then m=1; else m=0; fi
    else
      m=1
    fi
    printf '%s\t%s\t%s\t%s\n' "$id" "$size" "$m" "$preview"
  done <<<"$list"
  rm -f "$tmp"
}

print_rows() {  # stdin: id<TAB>크기<TAB>일치<TAB>미리보기
  if [ "$TSV" = 1 ]; then
    cut -f1,2,4
  else
    while IFS=$'\t' read -r id size _ preview; do
      printf '%7s  %8s  %s\n' "$id" "$(human "$size")" "$preview"
    done
  fi
}

confirm() {  # $1 = 질문
  [ "$YES" = 1 ] && return 0
  [ -t 0 ] || die "확인이 필요합니다 (비대화형에서는 -y 사용)"
  local ans
  read -r -p "$1 [y/N] " ans
  [ "$ans" = y ] || [ "$ans" = Y ]
}

# 파일(스캔 결과 중 선택된 행)의 항목을 삭제
delete_rows() {  # $1 = 파일(id<TAB>크기<TAB>일치<TAB>미리보기)
  local n
  n=$(wc -l <"$1")
  [ "$n" -gt 0 ] || { echo "대상이 없습니다."; return 0; }
  awk -F'\t' '{print $1 "\t" $4}' "$1" | CH delete || die "삭제 실패"
  "$CLIPMETA" prune >/dev/null 2>&1 || true
  echo "${n}개 삭제했습니다."
}

cmd_stats() {
  local f count total dbsize
  f=$(mktemp)
  scan >"$f" || die "목록을 읽지 못했습니다"
  count=$(wc -l <"$f")
  total=$(awk -F'\t' '{s+=$2} END{print s+0}' "$f")
  dbsize=$(stat -c %s "$DB" 2>/dev/null || echo 0)
  echo "항목 수      : $count"
  echo "내용 총 크기 : $(human "$total")"
  echo "DB 파일 크기 : $(human "$dbsize")"
  if [ "$dbsize" -gt $((total * 3 + 1048576)) ]; then
    echo "  → DB 가 내용보다 훨씬 큽니다. 'clipctl compact' 로 줄일 수 있습니다."
  fi
  echo
  echo "큰 항목 TOP 5:"
  sort -t$'\t' -k2 -nr "$f" | head -5 | TSV=0 print_rows
  rm -f "$f"
}

cmd_find() {
  [ -n "$PATTERN" ] || die "키워드가 필요합니다"
  local f
  f=$(mktemp)
  scan "$PATTERN" | awk -F'\t' '$3==1' >"$f"
  if [ "$TSV" != 1 ]; then echo "일치: $(wc -l <"$f")개"; fi
  print_rows <"$f"
  rm -f "$f"
}

cmd_delete() {
  [ -n "$PATTERN" ] || die "키워드가 필요합니다"
  local f n
  f=$(mktemp)
  scan "$PATTERN" | awk -F'\t' '$3==1' >"$f"
  n=$(wc -l <"$f")
  if [ "$n" -eq 0 ]; then echo "일치하는 항목이 없습니다."; rm -f "$f"; return 0; fi
  echo "일치: ${n}개"
  print_rows <"$f" | head -30
  [ "$n" -gt 30 ] && echo "  … 외 $((n - 30))개"
  if [ "$DRY" = 1 ]; then rm -f "$f"; return 0; fi
  if confirm "${n}개를 삭제할까요?"; then delete_rows "$f"; else echo "취소했습니다."; fi
  rm -f "$f"
}

cmd_big() {
  local kb="${1:-10}" f
  f=$(mktemp)
  scan | awk -F'\t' -v t=$((kb * 1024)) '$2>=t' | sort -t$'\t' -k2 -nr >"$f"
  if [ "$TSV" != 1 ]; then echo "${kb}KB 이상: $(wc -l <"$f")개"; fi
  print_rows <"$f"
  rm -f "$f"
}

cmd_delete_big() {
  local kb="${1:-}" f n
  [ -n "$kb" ] || die "KB 기준이 필요합니다"
  f=$(mktemp)
  scan | awk -F'\t' -v t=$((kb * 1024)) '$2>=t' >"$f"
  n=$(wc -l <"$f")
  if [ "$n" -eq 0 ]; then echo "${kb}KB 이상 항목이 없습니다."; rm -f "$f"; return 0; fi
  echo "${kb}KB 이상: ${n}개"
  print_rows <"$f" | head -30
  if [ "$DRY" = 1 ]; then rm -f "$f"; return 0; fi
  if confirm "${n}개를 삭제할까요?"; then delete_rows "$f"; else echo "취소했습니다."; fi
  rm -f "$f"
}

cmd_wipe() {
  local n
  n=$(CH list | wc -l)
  [ "$n" -gt 0 ] || { echo "이력이 비어 있습니다."; return 0; }
  if confirm "이력 ${n}개를 전부 삭제할까요?"; then CH wipe && echo "전체 삭제했습니다."; else echo "취소했습니다."; fi
}

# DB 재구성: 서비스 중지 → 백업 → 새 DB 에 오래된 것부터 다시 저장 → 개수/내용 검증 → 교체
# (trap 은 함수가 끝난 뒤 스크립트 종료 시점에 실행되므로 복구에 쓰는 변수는 전역이어야 함)
COMPACT_NEW="" COMPACT_WAS_ACTIVE=0
compact_restore() {
  if [ "$COMPACT_WAS_ACTIVE" = 1 ]; then systemctl --user start "$SERVICE" 2>/dev/null; fi
  [ -n "$COMPACT_NEW" ] && rm -f "$COMPACT_NEW"
  return 0
}

cmd_compact() {
  local new="$DB.new" bak before after count_old count_new h_old h_new id
  [ -f "$DB" ] || die "DB 가 없습니다: $DB"
  before=$(stat -c %s "$DB")
  bak="$DB.bak-$(date +%Y%m%d-%H%M%S)"
  COMPACT_NEW="$new"

  if systemctl --user is-active -q "$SERVICE" 2>/dev/null; then COMPACT_WAS_ACTIVE=1; fi
  trap compact_restore EXIT
  if [ "$COMPACT_WAS_ACTIVE" = 1 ]; then systemctl --user stop "$SERVICE"; fi

  cp -a "$DB" "$bak" || die "백업 실패"
  rm -f "$new"
  count_old=$(CH list | wc -l)
  h_old=$(CH -preview-width 1000000 list | cut -f2- | sha1sum | cut -d' ' -f1)

  # list 는 최신순 → tac 로 오래된 것부터 저장해야 순서가 유지됨
  CH list | cut -f1 | tac | while read -r id; do
    # 중복 검색을 꺼서(-max-dedupe-search 0) 이력을 있는 그대로 옮김 (끄지 않으면 가까운 중복이 합쳐져 개수가 달라짐)
    CH decode "$id" | "$CLIPHIST" -db-path "$new" -max-items 100000 -max-dedupe-search 0 store
  done

  count_new=$("$CLIPHIST" -db-path "$new" list | wc -l)
  h_new=$("$CLIPHIST" -db-path "$new" -preview-width 1000000 list | cut -f2- | sha1sum | cut -d' ' -f1)
  if [ "$count_old" != "$count_new" ] || [ "$h_old" != "$h_new" ]; then
    echo "검증 실패 (개수 $count_old → $count_new, 내용 해시 불일치). 원본을 유지합니다." >&2
    return 1
  fi

  # 이력 순서를 그대로 옮겼으므로 같은 위치끼리 대응 (최신순): 옛 번호 → 새 번호
  pairs=$(paste <(CH list | cut -f1) <("$CLIPHIST" -db-path "$new" list | cut -f1))
  mv "$new" "$DB" || die "교체 실패 (백업: $bak)"
  if ! printf '%s\n' "$pairs" | "$CLIPMETA" remap >/dev/null 2>&1; then
    echo "경고: 부가 정보(시각·앱·횟수) 번호 이동에 실패했습니다" >&2
  fi
  after=$(stat -c %s "$DB")
  # 오래된 백업은 최근 2개만 유지
  ls -1t "$DB".bak-* 2>/dev/null | tail -n +3 | xargs -r rm -f
  echo "완료: ${count_new}개 유지, DB $(human "$before") → $(human "$after")"
  echo "백업: $bak"
}

# ---- 인자 처리 ----
CMD="${1:-}"
[ -n "$CMD" ] || { usage; exit 1; }
shift

GREP_OPTS=(-F -i)
REGEX=0 CASE=0 YES=0 DRY=0 TSV=0
PATTERN="" POS=()
for arg in "$@"; do
  case "$arg" in
    -E) REGEX=1 ;;
    -s) CASE=1 ;;
    -y) YES=1 ;;
    -n) DRY=1 ;;
    --tsv) TSV=1 ;;
    -h|--help) usage; exit 0 ;;
    *) POS+=("$arg") ;;
  esac
done
GREP_OPTS=()
[ "$REGEX" = 1 ] && GREP_OPTS+=(-E) || GREP_OPTS+=(-F)
[ "$CASE" = 1 ] || GREP_OPTS+=(-i)
PATTERN="${POS[0]:-}"

case "$CMD" in
  stats) cmd_stats ;;
  find) cmd_find ;;
  delete) cmd_delete ;;
  big) cmd_big "${POS[0]:-10}" ;;
  delete-big) cmd_delete_big "${POS[0]:-}" ;;
  compact) cmd_compact ;;
  wipe) cmd_wipe ;;
  -h|--help|help) usage ;;
  *) usage; exit 1 ;;
esac
