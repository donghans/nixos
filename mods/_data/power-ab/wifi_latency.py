#!/usr/bin/env python3
"""wifi_latency — Wi-Fi 절전(power_save)을 켠/끈 구간을 번갈아(ABAB) 핑으로 재서 지연(평균/95%/최대)과 손실을 비교한다. **root 로 실행**.
  sudo systemd-run --unit=wifi-lat --collect --setenv=PATH=... <python3> wifi_latency.py <iw 경로> [구간 초=90] [인터페이스]
끝나면(오류 포함) 절전을 원래 값으로 되돌린다. 결과는 /tmp/wifi-latency.json."""
import json, os, re, statistics, subprocess, sys, time

os.environ["PATH"] = "/run/current-system/sw/bin:/run/wrappers/bin:" + os.environ.get("PATH", "")   # systemd-run 서비스의 PATH 는 거의 비어 있음(ip, ping 필요)

IW = sys.argv[1]
SEC = int(sys.argv[2]) if len(sys.argv) > 2 else 90
IFACE = sys.argv[3] if len(sys.argv) > 3 else "wlan0"
OUT = "/tmp/wifi-latency.json"


def run(*a, **k):
    return subprocess.run(a, capture_output=True, text=True, **k)


def get_ps():
    m = re.search(r"Power save:\s*(\w+)", run(IW, "dev", IFACE, "get", "power_save").stdout)
    return m[1] if m else "off"


def gateway():
    m = re.search(r"default via (\S+)", run("ip", "route", "show", "default").stdout)
    return m[1] if m else None


def ping(host, seconds, interval):
    """[RTT ms 목록], 보낸 개수, 받은 개수"""
    r = run("ping", "-n", "-i", str(interval), "-w", str(seconds), host)
    rtts = [float(x) for x in re.findall(r"time=([\d.]+) ms", r.stdout)]
    m = re.search(r"(\d+) packets transmitted, (\d+) received", r.stdout)
    return rtts, int(m[1]) if m else 0, int(m[2]) if m else 0


def summarize(rtts, sent, got):
    if not rtts:
        return {"sent": sent, "recv": got, "loss_pct": 100.0}
    s = sorted(rtts)
    return {"sent": sent, "recv": got, "loss_pct": round(100 * (sent - got) / max(sent, 1), 2), "avg_ms": round(statistics.fmean(rtts), 1),
            "median_ms": round(statistics.median(rtts), 1), "p95_ms": round(s[int(len(s) * 0.95) - 1], 1), "max_ms": round(s[-1], 1)}


def main():
    orig, gw, results = get_ps(), gateway(), []
    link = run(IW, "dev", IFACE, "link").stdout
    print(f"시작: 원래 절전={orig} 게이트웨이={gw}")
    try:
        for i, state in enumerate(("off", "on", "off", "on")):
            run(IW, "dev", IFACE, "set", "power_save", state)
            time.sleep(8)                                       # 드라이버가 적용될 시간
            r = {"state": state, "ps_now": get_ps()}
            if gw:
                r["gateway"] = summarize(*ping(gw, SEC // 2, 0.2))
            r["internet"] = summarize(*ping("1.1.1.1", SEC // 2, 0.5))
            results.append(r)
            print(i, json.dumps(r, ensure_ascii=False), flush=True)
            json.dump({"link": link, "results": results}, open(OUT, "w"), ensure_ascii=False, indent=1)
    finally:
        run(IW, "dev", IFACE, "set", "power_save", orig)
        print("원래 절전 값으로 복구:", get_ps(), flush=True)


if __name__ == "__main__":
    main()
