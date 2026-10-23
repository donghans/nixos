#!/bin/sh
# 컨테이너 묶음 켬(A) / 끔(B) 번갈아 — 상시 떠 있는 컨테이너들의 전력 비용(깨움·메모리·디스크). 컨테이너는 정상 종료(docker stop)·시작(docker start)만 하고 삭제·볼륨 변경은 하지 않는다.
# 사용: CONTAINERS="vectordb chat-mongodb chat-meilisearch rag_api LibreChat" SEG=300 PAIRS=3 containers_abab.sh   (덮개 닫고 배터리, 시작 순서대로 적는다 — 끌 때는 거꾸로)
# 켠 직후의 기동 비용(인덱싱·복구)이 있어 SETTLE 을 길게(기본 150초) 잡는다. 끝나면 처음에 떠 있던 컨테이너만 다시 켠다.
SETTLE=${SETTLE:-150}   # abab_lib.sh 가 SETTLE 기본값(40)을 먼저 채우므로 불러오기 전에 정한다
. "$(dirname "$0")/abab_lib.sh"
CONTAINERS=${CONTAINERS:?CONTAINERS=\"이름 이름 …\" (시작 순서대로)}
DOCKER=${DOCKER:-docker}
_running() { [ "$($DOCKER inspect -f '{{.State.Running}}' "$1" 2>/dev/null)" = true ]; }
_rev() { _r=""; for _c in "$@"; do _r="$_c $_r"; done; echo $_r; }
WAS_RUNNING=""; for _c in $CONTAINERS; do _running "$_c" && WAS_RUNNING="$WAS_RUNNING $_c"; done
abab_set_a()    { for _c in $CONTAINERS; do _running "$_c" || $DOCKER start "$_c" >/dev/null || return 1; done; }
abab_set_b()    { for _c in $(_rev $CONTAINERS); do ! _running "$_c" || $DOCKER stop -t 30 "$_c" >/dev/null || return 1; done; }
abab_verify_a() { for _c in $CONTAINERS; do _running "$_c" || return 1; done; }
abab_verify_b() { for _c in $CONTAINERS; do ! _running "$_c" || return 1; done; }
abab_restore()  { for _c in $CONTAINERS; do case " $WAS_RUNNING " in *" $_c "*) _running "$_c" || $DOCKER start "$_c" >/dev/null ;; *) ! _running "$_c" || $DOCKER stop -t 30 "$_c" >/dev/null ;; esac; done; echo "컨테이너 복구: 켜짐=$(for _c in $CONTAINERS; do _running "$_c" && printf '%s ' "$_c"; done)"; }
AB_ARGS="--ignore-app mongod --ignore-app meilisearch --ignore-app postgres $AB_ARGS"
abab_run
