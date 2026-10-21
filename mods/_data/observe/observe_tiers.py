"""observe_tiers — 단계형 eBPF 집계(상시 계측이 아니라 **시간 제한형 정밀 모드**). 수집기(root)가 bpftrace 를 자식으로 띄워 30초마다 프로세스(tgid)별 집계를 표본 흐름에 합친다.
단계(2026-10-21 실측, 코어 1개 기준 비용 / 정확성 — 장부 #61):
  sample  약 18.6Hz(53,711µs) CPU 점유 샘플링   0.12%(부하와 무관)   통계적 추정 — 정수 Hz 는 1초 주기 작업과 위상이 고정돼 편향되므로 비조화 주기 사용
  counts  `sched_switch` 전환 합계    0.62%(전환 수에 비례)      프로세스별 총 전환(자발+비자발) /proc 대비 98%
  full    자발·비자발·on-CPU 시간    1.8%(전환 수에 비례)       /proc 모든 스레드 합과 99%, CPU 시간 101%
안전장치: ① 제한 시간(`--for`, 최대 60분)이 지나면 자동으로 끈다 ② counts·full 은 시스템 전환이 초당 GUARD 를 넘으면 스스로 멈춘다(비용이 부하에 비례하므로) ③ 수집기가 끝나면 자식도 끝낸다.
개인정보: pid·프로세스 이름(comm)·횟수/시간 합계만. 순수 계산과 실행기를 분리해 시험한다."""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time

INTERVAL = 30
GUARD_SW_PER_S = 15000          # 이 이상이면 counts·full 은 비용이 코어의 10% 를 넘기 시작해 스스로 멈춘다(2026-10-21: 3,022/s 에서 full 1.8%)
MAX_MINUTES = 60
# 샘플링 주기: 정수 Hz(19·99 등)는 1초 주기로 일하는 프로세스(Netdata 등)와 정수비라 위상이 고정돼 한쪽 위상만 계속 찍힌다(2026-10-21 실측: netdata 가 L0 값의 약 3배로 과대 추정).
# 1/(18+0.618…)초 = 53,711µs 로 잡으면 1초마다 위상이 0.618 주기씩 이동해 골고루(저불일치 수열) 찍힌다.
SAMPLE_PERIOD_US = 53711
SAMPLE_HZ = 1e6 / SAMPLE_PERIOD_US          # 실효 주파수(약 18.62Hz) — 점유율 계산에 쓴다

TIERS = {
    "sample": {"label": "샘플링(E1)", "cost": "코어 약 0.12% (부하와 무관)", "accuracy": "통계적 추정(1초 주기 에일리어싱을 피하는 비조화 주기, 작은 프로세스는 오차 큼)", "gives": "프로세스별 CPU 점유 추정"},
    "counts": {"label": "전환 합계(E2)", "cost": "코어 약 0.6% (전환 3천/s 기준, 부하에 비례)", "accuracy": "프로세스별 총 전환 98%", "gives": "프로세스별 총 문맥 전환/s(자발+비자발, 짧게 사는 스레드 포함)"},
    "full": {"label": "전체(E3)", "cost": "코어 약 1.8% (전환 3천/s 기준, 부하에 비례)", "accuracy": "자발 전환 99%, CPU 시간 101%", "gives": "프로세스별 자발/비자발 전환/s·on-CPU 시간(코어 1개=100%)"},
}

_HDR = "#include <linux/sched.h>\n"
_TICK = 'printf("TICK %llu\\n", nsecs);'


def script(tier, interval=INTERVAL):
    """tier 의 bpftrace 프로그램. 맵은 interval 초마다 출력하고 비운다."""
    if tier == "sample":
        return (_HDR + f"profile:us:{SAMPLE_PERIOD_US} {{ @cpu[((struct task_struct *)curtask)->tgid] = count(); }}\n"
                f"interval:s:{interval} {{ print(@cpu); clear(@cpu); {_TICK} }}\n")
    if tier == "counts":
        return f"tracepoint:sched:sched_switch {{ @sw[pid] = count(); }}\ninterval:s:{interval} {{ print(@sw); clear(@sw); {_TICK} }}\n"
    if tier == "full":
        return (_HDR + "tracepoint:sched:sched_switch {\n"
                "  $t = ((struct task_struct *)curtask)->tgid;\n"
                "  if (@start[args->prev_pid]) { @cpu_ns[$t] = sum(nsecs - @start[args->prev_pid]); }\n"
                "  if (args->prev_state == 0) { @invol[$t] = count(); } else { @vol[$t] = count(); }\n"
                "  @start[args->next_pid] = nsecs;\n}\n"
                f"interval:s:{interval} {{ print(@vol); print(@invol); print(@cpu_ns); clear(@vol); clear(@invol); clear(@cpu_ns); clear(@start); {_TICK} }}\n")
    raise ValueError(f"알 수 없는 단계: {tier} (sample|counts|full)")


def parse_stream(lines):
    """bpftrace -f json 출력 줄들 → 간격마다 {"maps": {이름: {pid(str): 값}}, "tick_ns": 정수} 를 하나씩 내보낸다(TICK 줄이 간격의 끝). 깨진 줄은 건너뛴다."""
    cur = {}
    for raw in lines:
        try:
            o = json.loads(raw)
        except ValueError:
            continue
        if o.get("type") == "map":
            for k, v in (o.get("data") or {}).items():
                cur[k.lstrip("@")] = v if isinstance(v, dict) else {}
        elif o.get("type") == "printf" and str(o.get("data", "")).startswith("TICK"):
            try:
                tick = int(str(o["data"]).split()[1])
            except (IndexError, ValueError):
                tick = 0
            yield {"maps": cur, "tick_ns": tick}
            cur = {}


def summarize(tier, rec, dt, resolve, top=16):
    """한 간격의 집계 → 표본에 넣을 dict. resolve(pid)→프로세스 이름. pid 0(idle)은 뺀다. 반환 {"tier","dt","procs":[…],"sw_total_s"(counts·full), "samples"(sample)}."""
    m = rec["maps"]
    dt = max(dt, 1e-6)
    out = {"tier": tier, "dt": round(dt, 1), "procs": []}
    if tier == "sample":
        cpu = {p: v for p, v in (m.get("cpu") or {}).items() if p != "0"}
        out["samples"] = sum(cpu.values())
        rows = [{"pid": int(p), "comm": resolve(int(p)), "cpu_core_pct": round(v / (SAMPLE_HZ * dt) * 100, 2)} for p, v in cpu.items()]
        out["procs"] = sorted(rows, key=lambda r: -r["cpu_core_pct"])[:top]
    elif tier == "counts":
        sw = {p: v for p, v in (m.get("sw") or {}).items() if p != "0"}
        out["sw_total_s"] = round(sum(sw.values()) / dt, 1)
        rows = [{"pid": int(p), "comm": resolve(int(p)), "sw_s": round(v / dt, 1)} for p, v in sw.items()]
        out["procs"] = sorted(rows, key=lambda r: -r["sw_s"])[:top]
    else:
        vol, inv, cpu = (m.get("vol") or {}), (m.get("invol") or {}), (m.get("cpu_ns") or {})
        pids = {p for p in set(vol) | set(inv) | set(cpu) if p != "0"}
        out["sw_total_s"] = round((sum(vol.values()) + sum(inv.values())) / dt, 1)
        rows = [{"pid": int(p), "comm": resolve(int(p)), "cpu_core_pct": round(cpu.get(p, 0) / dt / 1e9 * 100, 2), "vol_s": round(vol.get(p, 0) / dt, 1), "invol_s": round(inv.get(p, 0) / dt, 1)} for p in pids]
        out["procs"] = sorted(rows, key=lambda r: -(r["cpu_core_pct"] + r["vol_s"] / 100))[:top]
    return out


def _comm_of(pid, cache={}):
    if pid in cache:
        return cache[pid]
    try:
        name = open(f"/proc/{pid}/comm").read().strip()
    except OSError:
        name = "?"
    if len(cache) > 4096:
        cache.clear()
    cache[pid] = name
    return name


class Runner:
    """bpftrace 자식 프로세스를 단계·제한 시간에 맞춰 켜고 끈다. 수집기가 매 반복마다 ensure()/take() 를 부른다."""

    def __init__(self, bpftrace, popen=subprocess.Popen, resolve=_comm_of, clock=time.time, interval=INTERVAL):
        self.bpftrace, self.popen, self.resolve, self.clock, self.interval = bpftrace, popen, resolve, clock, interval
        self.proc, self.tier, self.until = None, None, 0.0
        self._lock = threading.Lock()
        self._latest = None
        self.stopped_reason = None
        self._thread = None

    @property
    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def ensure(self, want):
        """want = {"tier": …, "until": epoch} 또는 None. 요구와 현재가 다르면 맞춘다. 반환: 지금 실행 중이면 True."""
        now = self.clock()
        if not want or not self.bpftrace or want.get("tier") not in TIERS or float(want.get("until", 0)) <= now:
            if self.proc is not None:
                self.stop("제한 시간 끝" if want and float(want.get("until", 0)) <= now else "꺼짐")
            return False
        if self.running and self.tier == want["tier"]:
            return True
        if self.proc is not None:
            self.stop("단계 변경")
        until = min(float(want["until"]), now + MAX_MINUTES * 60)
        try:
            self.proc = self.popen([self.bpftrace, "-f", "json", "-e", script(want["tier"], self.interval)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        except OSError as e:
            self.proc, self.stopped_reason = None, f"실행 실패: {e}"
            return False
        self.tier, self.until, self.stopped_reason, self._latest = want["tier"], until, None, None
        self._thread = threading.Thread(target=self._read, args=(self.proc, self.tier), daemon=True)
        self._thread.start()
        return True

    def _read(self, proc, tier):
        last = time.monotonic()
        for rec in parse_stream(proc.stdout):
            now = time.monotonic()
            dt, last = now - last, now
            s = summarize(tier, rec, dt, self.resolve)
            s["tick_t"] = round(self.clock(), 1)
            with self._lock:
                self._latest = s
            if tier != "sample" and s.get("sw_total_s", 0) > GUARD_SW_PER_S:
                self.stopped_reason = f"전환 {s['sw_total_s']:.0f}/s 가 상한 {GUARD_SW_PER_S}/s 를 넘어 스스로 멈춤(비용이 부하에 비례)"
                try:
                    proc.terminate()
                except OSError:
                    pass
                return

    def take(self):
        """아직 표본에 넣지 않은 가장 최근 집계 하나(없으면 None). 가져가면 비운다."""
        with self._lock:
            s, self._latest = self._latest, None
        return s

    def stop(self, reason=None):
        p, self.proc = self.proc, None
        if reason and not self.stopped_reason:
            self.stopped_reason = reason
        if p is None:
            return
        try:
            p.terminate()
            p.wait(timeout=3)
        except Exception:
            try:
                p.kill()
            except OSError:
                pass
