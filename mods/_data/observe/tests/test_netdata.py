#!/usr/bin/env python3
"""Netdata 어댑터 시험(가짜 HTTP 서버 — 응답 모양은 실제 Netdata v2.10 API 에서 복사): 신호 정의·곱셈·공백/꺼짐 처리·앱 CPU·지원하지 않는 항목."""
import http.server, json, os, sys, threading, time, urllib.parse
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(os.path.dirname(ROOT), "_testkit"))
from harness import checker
check, finish = checker()

T0 = 1_000_000
# 차트별 응답(점 하나짜리 평균 / 시계열). None 은 Netdata 가 꺼져 있던 칸.
AVG = {
    "cpu.powercap_intel_rapl_zone_psys": {"labels": ["time", "power"], "data": [[T0, 5.5]]},
    "cpu.powercap_intel_rapl_zone_package-0": {"labels": ["time", "power"], "data": [[T0, 2.0]]},
    "system.cpu": {"labels": ["time", "guest_nice", "guest", "steal", "softirq", "irq", "user", "system", "nice", "iowait", "idle"], "data": [[T0, 0, 0, 0, 0.5, 0.2, 3.0, 1.0, 0, 9.0, 86.3]]},
    "system.ctxt": {"labels": ["time", "switches"], "data": [[T0, 2500.0]]},
    "system.intr": {"labels": ["time", "interrupts"], "data": [[T0, 1400.0]]},
    "system.net": {"labels": ["time", "received", "sent"], "data": [[T0, 30.0, -50.0]]},
    "system.io": {"labels": ["time", "reads", "writes"], "data": [[T0, 12.0, -34.0]]},
    "system.forks": {"labels": ["time", "started"], "data": [[T0, 3.0]]},
    "sensors.temperature_nvme-pci-0200_temp1_Composite_input": {"labels": ["time", "input"], "data": [[T0, 33.5]]},
}
SERIES = {  # 시계열(점 여러 개): 배터리 전압·전류, 그리고 커버리지용 system.ctxt
    "sensors.voltage_BAT1-acpi-0_in0_input": {"labels": ["time", "input"], "data": [[T0 + i, 15.0] for i in range(10)]},
    "sensors.curr_BAT1-acpi-0_curr1_input": {"labels": ["time", "input"], "data": [[T0 + i, 0.4 if i < 5 else 0.6] for i in range(10)]},
}
CHARTS = {"charts": {k: {"units": "x"} for k in list(AVG) + list(SERIES)}}
APPS = {"result": {"labels": ["time", "app.start-hyprland_cpu_utilization@u", "app._tailscaled-wra_cpu_utilization@u", "app.kernel_cpu_utilization@u", "app.idle_cpu_utilization@u"],
                   "data": [[T0, [50.5, 1, 2], [2.7, 1, 2], [0.8, 1, 2], [0, 1, 2]]]}}
STATE = {"down_chart": None, "blank": False, "opts": [], "pts": []}

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _send(self, obj, code=200):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query)
        if u.path == "/api/v1/info": return self._send({"version": "v2.10.3"})
        if u.path == "/api/v1/charts": return self._send(CHARTS)
        if u.path == "/api/v3/data": return self._send(APPS)
        if u.path == "/api/v1/data":
            ch = q["chart"][0]; n = int(q.get("points", ["1"])[0])
            STATE["opts"].append(q.get("options", [""])[0]); STATE["pts"].append(n)
            if STATE["blank"]:
                lab = (AVG.get(ch) or SERIES.get(ch) or {"labels": ["time", "v"]})["labels"]
                return self._send({"labels": lab, "data": [[T0 + i] + [None] * (len(lab) - 1) for i in range(max(1, n))]})
            if n == 1 and ch in AVG: return self._send(AVG[ch])
            if ch in AVG and ch != "system.ctxt": return self._send({"labels": AVG[ch]["labels"], "data": [[T0 + i * 30] + AVG[ch]["data"][0][1:] for i in range(n)]})
            if ch in SERIES: return self._send(SERIES[ch])
            if ch == "system.ctxt":                               # 커버리지: 앞 절반만 데이터
                rows = [[T0 + i * 5, 2500.0 if i < n // 2 else None] for i in range(n)]
                return self._send({"labels": ["time", "switches"], "data": rows} if STATE.get("half") else AVG[ch] if n == 1 else {"labels": ["time", "switches"], "data": [[T0 + i * 5, 2500.0] for i in range(n)]})
            return self._send({"error": "no such chart"}, 404)
        self._send({}, 404)

srv = http.server.HTTPServer(("127.0.0.1", 0), H); port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
os.environ["OBSERVE_NETDATA"] = f"http://127.0.0.1:{port}"
import observe_netdata as nd
nd.BASE = os.environ["OBSERVE_NETDATA"]; nd.reset_cache()

check("available: 응답하면 True", nd.available(ttl=0) is True)
sig = nd.signals(T0, T0 + 120)
check("신호: RAPL psys·패키지는 그대로(W)", sig["psys_w"] == 5.5 and sig["pkg_w"] == 2.0, str(sig))
check("신호: 전체 CPU 는 idle·iowait 를 뺀 합(0.5+0.2+3+1 = 4.7, 전체 대비)", abs(sig["cpu_all_pct"] - 4.7) < 1e-9, str(sig["cpu_all_pct"]))
check("신호: 시스템 전체 문맥 전환·인터럽트", sig["ctxsw_all_s"] == 2500.0 and sig["intr_all_s"] == 1400.0)
check("신호: 네트워크 송신·디스크 쓰기는 절댓값(음수로 오는 차원)", sig["net_rx_kbps"] == 30.0 and sig["net_tx_kbps"] == 50.0 and sig["disk_read_kibs"] == 12.0 and sig["disk_write_kibs"] == 34.0, str(sig))
check("신호: NVMe 온도는 차트 이름을 찾아서(sensors.temperature_nvme*)", sig["nvme_temp_c"] == 33.5)
check("신호: 배터리 V×I 는 점마다 곱한 평균(15×0.4 5개, 15×0.6 5개 → 7.5)", abs(sig["batt_vi_w"] - 7.5) < 1e-9, str(sig["batt_vi_w"]))
check("신호: 모든 항목에 정의·단위가 문서화됨(SIGNALS)", set(nd.SIGNALS) == set(sig) and all(len(v) == 3 and v[2] for v in nd.SIGNALS.values()))
apps = nd.top_apps(T0, T0 + 120, 3)
check("앱 CPU: 값 큰 순·0 은 제외·그룹 이름 정리(앞의 _ 제거, @노드 제거)", [a for a, _ in apps] == ["start-hyprland", "tailscaled-wra", "kernel"] and apps[0][1] == 50.5, str(apps))
snap = nd.snapshot(T0, T0 + 120)
check("snapshot: 커버리지 1·신호·앱을 한 번에", snap and snap["coverage"] == 1.0 and snap["signals"]["psys_w"] == 5.5 and snap["apps_cpu"][0][0] == "start-hyprland", str(snap))
check("지원하지 않는 항목: 앱별 문맥 전환 함수가 어댑터에 없다(메인 스레드만 세는 값이라 의도적으로 제외)", not hasattr(nd, "top_apps_ctxsw") and "context_switches" not in open(os.path.join(ROOT, "observe_netdata.py")).read().split("def _get")[1])
STATE["blank"] = True
check("전 구간 공백(Netdata 가 꺼져 있던 시간): 구간 평균이 None", nd.window_avg("system.ctxt", T0, T0 + 60) is None and nd.signals(T0, T0 + 60)["psys_w"] is None)
check("전 구간 공백: 커버리지 0, snapshot 은 신호가 전부 None(오류 아님)", nd.coverage(T0, T0 + 60) == 0.0 and all(v is None for v in nd.snapshot(T0, T0 + 60)["signals"].values()))
STATE["blank"] = False
# --- 구간 평균은 묶음 단위로 넓어지지 않게(options=unaligned) 같은 폭의 점 여러 개를 받아 직접 평균
STATE["opts"].clear(); STATE["pts"].clear()
avg = nd.window_avg("cpu.powercap_intel_rapl_zone_psys", T0, T0 + 240)
check("window_avg: 모든 요청이 options=unaligned 이고 points>1(한 점짜리 평균을 쓰지 않음 — Netdata 가 구간을 바깥으로 넓힘)", STATE["opts"] and set(STATE["opts"]) == {"unaligned"} and min(STATE["pts"]) > 1 and abs(avg["power"] - 5.5) < 1e-9, str((STATE, avg)))
# --- sample_series / bucket_mean / chart_list (window 병기·nd charts 용)
ss = nd.sample_series(T0, T0 + 120)
check("sample_series: 신호별 [(시각, 값)] — 수신·송신 부호 정리, 디스크 reads/writes, NVMe", ss.get("net_rx_kbps") and ss["net_tx_kbps"][0][1] == 50.0 and ss["disk_write_kibs"][0][1] == 34.0 and ss["nvme_temp_c"][0][1] == 33.5, str(ss))
check("bucket_mean: ±15초 안의 값만 평균, 없으면 None", nd.bucket_mean([(100, 1.0), (110, 3.0), (200, 9.0)], 105) == 2.0 and nd.bucket_mean([(100, 1.0)], 300) is None)
check("chart_list: 이름 조각 필터·정렬, 단위 포함", [c[0] for c in nd.chart_list("system.")] == sorted(k for k in CHARTS["charts"] if "system." in k) and nd.chart_list("rapl_zone_psys")[0][1] == "x")
srv.shutdown(); srv.server_close()
nd.reset_cache()
check("서버가 꺼지면 available False·snapshot None(분석은 '관측 공백'으로 계속)", nd.available(ttl=0) is False and nd.snapshot(T0, T0 + 60) is None)
try:
    nd._get("/api/v1/info", timeout=0.3); check("꺼진 서버 호출은 NetdataError", False)
except nd.NetdataError:
    check("꺼진 서버 호출은 NetdataError", True)
check("앱 이름 정리", nd.app_name("app._gvfsd-wrapped_cpu_utilization@abc") == "gvfsd-wrapped" and nd.app_name("app.kernel_cpu_utilization") == "kernel")
finish("netdata")
