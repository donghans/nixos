#!/bin/sh
# sbox-mem — 이 격리 컨테이너의 메모리 한도·사용·압박을 보여 준다 (plan dev-sandbox-pilot §29-27, S69 자각 장치).
# 한도는 두 겹이다: ① 이 컨테이너의 high(소프트 — 넘으면 느려질 뿐 죽지 않음) ② 호스트 쪽 sbox 전체 합계(여러 컨테이너가 같이 쓰므로 여기서는 보이지 않음).
# 새 작업(예: docker compose 로 DB 스택 전부 띄우기) 전에 부르면 좋다. 읽기 전용.
cg=/sys/fs/cgroup
n() { [ "$1" = max ] && echo "무제한" || awk -v b="$1" 'BEGIN{printf "%.2f GiB", b/1073741824}'; }
cur=$(cat $cg/memory.current 2>/dev/null || echo 0); high=$(cat $cg/memory.high 2>/dev/null || echo max); max=$(cat $cg/memory.max 2>/dev/null || echo max)
echo "메모리: 사용 $(n "$cur") / high(소프트) $(n "$high") / max $(n "$max")"
if [ "$high" != max ] && [ "$high" -gt 0 ] 2>/dev/null; then
  pct=$((cur * 100 / high)); echo "  high 대비 ${pct}%"
  [ "$pct" -ge 80 ] && echo "  ⚠ 한도에 가깝습니다 — 새 서비스를 더 띄우기 전에 아래 상위 프로세스·docker stats 를 확인하세요"
fi
ev=$(awk '$1=="high"{print $2}' $cg/memory.events 2>/dev/null); [ -n "$ev" ] && echo "  high 초과로 늦춰진 횟수(누적): $ev"
psi=$(awk '/^some/{print $2}' $cg/memory.pressure 2>/dev/null); [ -n "$psi" ] && echo "  메모리 압박(some): $psi (avg10 이 높으면 느려지는 중)"
echo "상위 프로세스(RSS):"; ps -eo rss,comm --sort=-rss 2>/dev/null | head -n 6 | awk 'NR>1{printf "  %7.0f MiB  %s\n", $1/1024, $2}'
if command -v docker >/dev/null 2>&1 && [ -n "$DOCKER_HOST" -o -S "/run/user/$(id -u)/docker.sock" ]; then
  export DOCKER_HOST="${DOCKER_HOST:-unix:///run/user/$(id -u)/docker.sock}"
  echo "docker 컨테이너:"; docker stats --no-stream --format '  {{.MemUsage}}  {{.Name}}' 2>/dev/null | head -n 10
fi
