#!/usr/bin/env python3
"""input_rate — **root**. 30초 동안 모든 입력 장치(/dev/input/event*)의 이벤트 **개수**를 장치별로 센다(SYN/MSC 제외; 눌린 키나 좌표 같은 내용은 읽어도 기록하지 않음).
입력 잡음이 화면 타이머나 절전을 방해하는지 볼 때 쓴다. 2026-10-20 높은 상태에서 30초 0건이었음."""
import glob, os, select, struct, time, collections
FMT="llHHi"; SZ=struct.calcsize(FMT)
devs={}
for d in sorted(glob.glob("/sys/class/input/event*")):
    try: name=open(d+"/device/name").read().strip()
    except OSError: continue
    try: devs[os.open("/dev/input/"+os.path.basename(d),os.O_RDONLY|os.O_NONBLOCK)]=(os.path.basename(d),name)
    except OSError: pass
cnt=collections.Counter(); typ=collections.defaultdict(collections.Counter)
end=time.time()+30
while time.time()<end:
    r,_,_=select.select(list(devs),[],[],1.0)
    for fd in r:
        data=os.read(fd,SZ*128)
        for i in range(0,len(data)-SZ+1,SZ):
            _,_,t,_,_=struct.unpack(FMT,data[i:i+SZ])
            if t not in (0,4): cnt[devs[fd]]+=1; typ[devs[fd]][t]+=1   # SYN/MSC 제외
print("30초 입력 이벤트 수(장치별, SYN/MSC 제외; 내용은 보지 않음):")
for (ev,name),n in cnt.most_common(): print(f"  {ev:<8}{name:<45}{n:>6}건  종류 {dict(typ[(ev,name)])}")
if not cnt: print("  (이벤트 없음)")
