"""observectl 공통 — 경로, 제어 파일, JSONL 기록/회전/조회, 시각 해석. 표준 라이브러리만 쓴다.

데이터 배치(기본 /var/lib/observe, OBSERVE_DATA_DIR 로 바꿔 시험):
  control.json    사용자가 쓰는 제어 파일(0664 root:users). 수집기 켜기/끄기, 수준(L0/L1), 간격, 컴포넌트별 로그 수준.
  requests/       사용자가 root 작업(wakers 등)을 요청하는 파일을 놓는 곳(스티키 1777).
  results/        수집기가 작업 결과를 쓰는 곳(모두 읽기 가능).
  data/           samples-YYYYMMDD.jsonl (수집기 표본). 보존: 일수·총 용량 제한.
사용자 이벤트 로그(displayui 등 유틸리티)는 ~/.local/state/observe/events-YYYYMMDD.jsonl.
개인정보: 키 입력 내용, URL, 명령 인자는 기록하지 않는다(프로세스는 comm 과 exe 이름만).
"""
import datetime, fcntl, glob, json, os, re, time

DATA_DIR = os.environ.get("OBSERVE_DATA_DIR", "/var/lib/observe")
CONTROL = os.path.join(DATA_DIR, "control.json")
REQ_DIR = os.path.join(DATA_DIR, "requests")
RES_DIR = os.path.join(DATA_DIR, "results")
SAMPLE_DIR = os.path.join(DATA_DIR, "data")


def state_dir():
    return os.environ.get("OBSERVE_STATE_DIR") or os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "observe")


LEVELS = {"trace": 0, "debug": 1, "info": 2, "warn": 3, "error": 4}

DEFAULT_CONTROL = {
    "enabled": False,                      # 수집기 표본 기록
    "level": "L0",                         # L0: 가볍게(30초) / L1: 프로파일(5초, 스레드·IO)
    "interval_s": {"L0": 30, "L1": 5},
    "components": {"*": "info", "displayui": "debug", "dispctl": "debug"},   # 이벤트 로그 수준(컴포넌트별, "*"=기본)
    "retention_days": 14,
    "max_total_mb": 1024,
    "mark": None,                          # 실험 조건 표지(observectl mark): {"cond": "A", "t": epoch, "note": ""}
    "ebpf": None,                          # 시간 제한형 정밀 모드(observectl ebpf on): {"tier": "sample|counts|full", "until": epoch}
}


def read_control(path=None):
    """제어 파일을 읽어 기본값과 합친다. 없거나 깨졌으면 기본값."""
    ctl = json.loads(json.dumps(DEFAULT_CONTROL))
    try:
        data = json.load(open(path or CONTROL))
    except (OSError, ValueError):
        return ctl
    for k, v in data.items():
        if isinstance(v, dict) and isinstance(ctl.get(k), dict):
            ctl[k].update(v)
        else:
            ctl[k] = v
    return ctl


def write_control(patch, path=None):
    """제어 파일에 patch 를 합쳐 **제자리에** 쓴다(systemd path 유닛이 변경을 감지하도록, 잠금 포함)."""
    p = path or CONTROL
    fd = os.open(p, os.O_RDWR | os.O_CREAT, 0o664)
    with os.fdopen(fd, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            cur = json.load(f)
        except ValueError:
            cur = {}
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(cur.get(k), dict):
                cur[k].update(v)
            else:
                cur[k] = v
        f.seek(0)
        f.truncate()
        json.dump(cur, f, ensure_ascii=False, indent=1)
        f.flush()
        fcntl.flock(f, fcntl.LOCK_UN)
    return read_control(p)


def level_for(component, ctl):
    """컴포넌트의 이벤트 로그 수준(숫자). 지정이 없으면 "*" → info."""
    comps = ctl.get("components", {})
    name = comps.get(component, comps.get("*", "info"))
    return LEVELS.get(str(name).lower(), LEVELS["info"])


def day_file(directory, prefix, t=None):
    d = datetime.datetime.fromtimestamp(t if t is not None else time.time())
    return os.path.join(directory, f"{prefix}-{d:%Y%m%d}.jsonl")


def append_jsonl(directory, prefix, obj, t=None):
    os.makedirs(directory, exist_ok=True)
    with open(day_file(directory, prefix, t), "a") as f:
        f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")


def prune(directory, prefix, days, max_mb):
    """오래된(days 초과) 파일을 지우고, 총 용량이 max_mb 를 넘으면 가장 오래된 것부터 지운다. 지운 파일 수를 돌려준다."""
    files = sorted(glob.glob(os.path.join(directory, prefix + "-*.jsonl")))
    removed = 0
    cutoff = time.time() - days * 86400
    for f in list(files):
        if os.path.getmtime(f) < cutoff:
            os.unlink(f)
            files.remove(f)
            removed += 1
    while files and sum(os.path.getsize(f) for f in files) > max_mb * 1024 * 1024 and len(files) > 1:
        os.unlink(files.pop(0))
        removed += 1
    return removed


SCHEMA = 4     # 표본 형식 버전. v2(2026-10-21): 단위가 이름에 드러나는 필드명. v3: proc 행의 ctxsw_vol_s 가 **모든 스레드 합**(v1·v2 는 메인 스레드만이라 멀티스레드 프로세스를 크게 과소 집계). v4: `apps`(앱 단위 합계, 전체 프로세스 포함) 추가.
_RENAME_PROC = {"cpu": "cpu_core_pct", "wake": "ctxsw_vol_s"}


def normalize_sample(o):
    """옛 형식 표본을 최신 이름으로 바꿔 돌려준다(원본 파일은 그대로). **v1·v2 만 legacy=True**(값의 뜻이 달라서); v3 는 `apps` 가 없을 뿐이라 legacy 가 아니다.
    v1→v2: pw.batt_w→batt_vi_w(순간 V×I), irq.cpu_busy_pct→cpu_all_pct(전체 CPU 대비 %), proc/thr 행 cpu→cpu_core_pct(코어 1개=100%), wake→ctxsw_vol_s(자발적 문맥 전환/s).
    v2→v3: **proc 행의 ctxsw_vol_s → ctxsw_vol_leader_s**(옛 값은 `/proc/<pid>/status` 의 메인 스레드 카운터뿐이라 멀티스레드 프로세스가 거의 0 으로 보임 — 합산·비교에 쓰면 안 됨).
    thr 행(L1)은 스레드 단위라 정확하므로 ctxsw_vol_s 를 그대로 둔다."""
    if not isinstance(o, dict) or o.get("v", 1) >= SCHEMA:
        return o
    orig = o.get("v", 1)
    if orig < 2:
        pw, irq = o.get("pw"), o.get("irq")
        if isinstance(pw, dict) and "batt_w" in pw:
            pw["batt_vi_w"] = pw.pop("batt_w")
        if isinstance(irq, dict) and "cpu_busy_pct" in irq:
            irq["cpu_all_pct"] = irq.pop("cpu_busy_pct")
        for key in ("proc", "thr"):
            for r in o.get(key) or []:
                if isinstance(r, dict):
                    for a, b in _RENAME_PROC.items():
                        if a in r:
                            r[b] = r.pop(a)
    if orig < 3:
        for r in o.get("proc") or []:
            if isinstance(r, dict) and "ctxsw_vol_s" in r:
                r["ctxsw_vol_leader_s"] = r.pop("ctxsw_vol_s")
    o["v"] = SCHEMA
    if orig < 3:
        o["legacy"] = True
    return o


def iter_jsonl(directory, prefix, since=None, until=None):
    """표본/이벤트를 시간순으로 돌려준다(키 "t" 가 epoch 초). 깨진 줄은 건너뛰고, **현재보다 미래 시각(+5분 초과)인 줄도 건너뛴다** —
    이 기기는 부팅 직후 약 30초 동안 시계가 9시간 앞서(RTC 가 로컬 시각 모드) 그때 기록된 표본의 t 가 가짜 미래 값이다."""
    horizon = time.time() + 300
    for f in sorted(glob.glob(os.path.join(directory, prefix + "-*.jsonl"))):
        m = re.search(r"-(\d{8})\.jsonl$", f)
        if m:
            day = datetime.datetime.strptime(m[1], "%Y%m%d").timestamp()
            if since is not None and day + 86400 < since:
                continue
            if until is not None and day > until:
                continue
        try:
            fh = open(f)
        except OSError:
            continue
        with fh:
            for line in fh:
                try:
                    o = json.loads(line)
                except ValueError:
                    continue
                t = o.get("t")
                if t is None or t > horizon or (since is not None and t < since) or (until is not None and t > until):
                    continue
                yield normalize_sample(o) if prefix == "samples" else o


def parse_when(s, now=None):
    """"11:20", "11:20:30", "-30m", "-2h", "2026-10-20 11:20", epoch 숫자 → epoch 초(로컬 시각 기준)."""
    now = now if now is not None else time.time()
    s = str(s).strip()
    m = re.fullmatch(r"-?(\d+(?:\.\d+)?)([smhd])", s)             # "30m" 과 "-30m" 모두 "30분 전"(CLI 에서 --since -30m 은 옵션으로 오해되므로 앞의 - 없이도 받음)
    if m:
        return now - float(m[1]) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m[2]]
    if re.fullmatch(r"\d{9,}(\.\d+)?", s):
        return float(s)
    m = re.fullmatch(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", s)
    if m:
        d = datetime.datetime.fromtimestamp(now).replace(hour=int(m[1]), minute=int(m[2]), second=int(m[3] or 0), microsecond=0)
        t = d.timestamp()
        return t if t <= now + 60 else t - 86400        # 미래 시각이면 어제로
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.datetime.strptime(s, fmt).timestamp()
        except ValueError:
            pass
    raise ValueError(f"시각을 해석할 수 없음: {s}")


def hms(t):
    return datetime.datetime.fromtimestamp(t).strftime("%H:%M:%S")
