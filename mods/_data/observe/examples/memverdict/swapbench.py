import mmap, os, random, sys, time, json
N_MB=int(sys.argv[1]); PG=4096; size=N_MB<<20; npg=size//PG
def vm():
    d={}
    for l in open('/proc/vmstat'):
        k,v=l.split(); d[k]=int(v)
    return d
def psi(kind):
    o={}
    for l in open(f'/proc/pressure/{kind}'):
        p=l.split(); kv=dict(x.split('=') for x in p[1:]); o[p[0]]=int(kv['total'])
    return o
def swaps():
    o={}
    for l in open('/proc/swaps').read().splitlines()[1:]:
        f=l.split(); o[f[0]]=int(f[3])*1024
    return o
def cg(name):
    path='/sys/fs/cgroup'+open('/proc/self/cgroup').read().strip().split(':')[2]
    return int(open(f'{path}/{name}').read())
def pct(x,p): x=sorted(x); return x[min(int(len(x)*p),len(x)-1)]
res={}
buf=mmap.mmap(-1,size)
v0,p0,s0,t0=vm(),psi('memory'),swaps(),time.monotonic()
chunk=os.urandom(1<<20)
for off in range(0,size,1<<20):
    buf[off:off+(1<<20)]=chunk[:1024]+os.urandom(1<<20)[1024:] if False else os.urandom(1<<20)
dt=time.monotonic()-t0; v1,p1,s1=vm(),psi('memory'),swaps()
res['fill']=dict(sec=round(dt,2),MiB_s=round(N_MB/dt),pswpout_pages=v1['pswpout']-v0['pswpout'],pswpin=v1['pswpin']-v0['pswpin'],
  swap_used_delta_MiB={k:round((s1[k]-s0.get(k,0))/(1<<20)) for k in s1},cg_swap_MiB=cg('memory.swap.current')>>20,cg_rss_MiB=cg('memory.current')>>20,
  host_mem_stall_ms=round((p1['some']-p0['some'])/1000))
time.sleep(1)
# 순차 읽기 2회
for r in range(2):
    v0,p0,t0=vm(),psi('memory'),time.monotonic(); x=0
    for off in range(0,size,PG): x+=buf[off]
    dt=time.monotonic()-t0; v1,p1=vm(),psi('memory')
    res[f'seq{r}']=dict(sec=round(dt,2),MiB_s=round(N_MB/dt),pswpin_pages=v1['pswpin']-v0['pswpin'],pswpout_pages=v1['pswpout']-v0['pswpout'],host_mem_stall_ms=round((p1['some']-p0['some'])/1000))
# 무작위 읽기(스왑 적중 최악 조건): 개별 지연
random.seed(1); idx=[random.randrange(npg) for _ in range(30000)]
lat=[]; v0,p0,t0=vm(),psi('memory'),time.monotonic()
for i in idx:
    a=time.perf_counter_ns(); x+=buf[i*PG]; lat.append(time.perf_counter_ns()-a)
dt=time.monotonic()-t0; v1,p1=vm(),psi('memory')
us=[l/1000 for l in lat]
res['rand']=dict(accesses=len(idx),sec=round(dt,2),per_s=round(len(idx)/dt),pswpin_pages=v1['pswpin']-v0['pswpin'],pswpout_pages=v1['pswpout']-v0['pswpout'],
  lat_us={k:round(pct(us,p),1) for k,p in (('p50',.5),('p90',.9),('p99',.99),('p999',.999))},max_us=round(max(us)),mean_us=round(sum(us)/len(us),1),host_mem_stall_ms=round((p1['some']-p0['some'])/1000))
# 기준선: 제한 안에 들어가는 작은 영역(상주) 무작위 읽기
small=memoryview(buf)[:64<<20]
for i in range(0,64<<20,PG): x+=small[i]
lat=[]
for i in random.sample(range(64<<20>>12),10000):
    a=time.perf_counter_ns(); x+=small[i*PG]; lat.append(time.perf_counter_ns()-a)
us=[l/1000 for l in lat]; res['resident_baseline_us']={k:round(pct(us,p),2) for k,p in (('p50',.5),('p99',.99))}
print(json.dumps(res,ensure_ascii=False,indent=1))
