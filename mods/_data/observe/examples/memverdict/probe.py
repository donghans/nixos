import time, json, sys
dur=float(sys.argv[1]); PG=4096
def pct(x,p): x=sorted(x); return x[min(int(len(x)*p),len(x)-1)]
sleep_over=[]; alloc=[]; t_end=time.monotonic()+dur; n=0
while time.monotonic()<t_end:
    a=time.perf_counter_ns(); time.sleep(0.001); sleep_over.append((time.perf_counter_ns()-a)/1000-1000)
    n+=1
    if n%50==0:                      # 약 0.1초마다 새 메모리 16MiB 를 받아 전부 건드리는 시간(앱 실행 때 겪는 페이지 폴트 비용)
        a=time.perf_counter_ns(); b=bytearray(16<<20)
        for i in range(0,16<<20,PG): b[i]=1
        alloc.append((time.perf_counter_ns()-a)/1e6); del b
r=lambda x,ps:{k:round(pct(x,p),2) for k,p in ps}
print(json.dumps(dict(n_sleep=len(sleep_over),sleep_overshoot_us=r(sleep_over,(('p50',.5),('p99',.99),('p999',.999))),sleep_max_us=round(max(sleep_over)),
  alloc16MiB_ms=r(alloc,(('p50',.5),('p99',.99))),alloc_max_ms=round(max(alloc),2),allocs=len(alloc)),ensure_ascii=False))
