# memverdict — 스왑 폭주 벤치마크와 영향 측정(2026-10-26)

`_plan/host-memory-verdict.md` 의 근거 시험 스크립트. 호스트에 부담을 주므로 다른 세션이 큰 일을 하지 않을 때만 돌린다.

- `swapbench.py <MiB>`: cgroup 메모리 제한 안에서 제한보다 큰 영역을 쓰고 읽어 스왑 경로(채우기·순차·무작위 읽기)의 처리량과 개별 접근 지연을 잰다.
  `cd / && systemd-run --user --scope -q -p MemoryMax=300M -p MemorySwapMax=3G python3 swapbench.py 1536`
- `probe.py <초>`: 별도 scope 에서 sleep(1ms) 초과 지연과 16MiB 새 메모리 받기 시간을 재서, 스왑 폭주가 **다른** 프로세스에 주는 영향을 본다(스레셔 유무 A/B).
  `systemd-run --user --scope -q python3 probe.py 10`
