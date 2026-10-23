import os,subprocess,time,sys,random,re
P="/nix/store/3jp4j0c6yqdx2pr5v8i10ac23py0a0al-perf-linux-7.0.12/bin/perf"
def waker(rate,secs):
    code="import os,time\nos.sched_setaffinity(0,{2})\nr=%d\nend=time.monotonic()+%d\nnx=time.monotonic()\nwhile time.monotonic()<end:\n  if r==0: time.sleep(0.5); continue\n  nx+=1/r; d=nx-time.monotonic()\n  time.sleep(d) if d>0 else None\n"%(rate,secs)
    return subprocess.Popen(["python3","-c",code])
ev="msr/tsc/,cstate_pkg/c2-residency/,cstate_pkg/c3-residency/,cstate_pkg/c6-residency/,cstate_pkg/c8-residency/,cstate_pkg/c10-residency/"
rates=[0,100,500,2000]*2; random.shuffle(rates)
for r in rates:
    w=waker(r,28); time.sleep(8)
    o=subprocess.run([P,"stat","-a","-x,","-e",ev,"--","sleep","15"],capture_output=True,text=True).stderr
    w.wait()
    v={}
    for l in o.splitlines():
        f=l.split(",")
        if len(f)>3 and f[0].isdigit(): v[f[2]]=int(f[0])
    tsc=v.get("msr/tsc/",1)
    # tsc 는 -a 로 전 CPU 합 → 패키지 값은 1 소켓이므로 CPU 수로 나눔
    n=os.cpu_count(); base=tsc/n
    print("rate %5d "%r+" ".join("%s=%.1f%%"%(k.split("/")[1].replace("-residency",""),100*x/base) for k,x in v.items() if k!="msr/tsc/"),flush=True)
