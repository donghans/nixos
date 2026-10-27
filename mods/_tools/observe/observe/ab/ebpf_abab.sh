#!/bin/sh
# eBPF `sample` 단계 켬(B) / 끔(A) 번갈아 — 정밀 모드 자체의 **전력** 비용(CPU 비용은 #61 에서 쟀지만 전력은 아직). 샘플링이 유휴 CPU 를 깨울 수 있다.
# 사용: ebpf_abab.sh   (덮개를 닫고 배터리에서, 손대지 않기)
. "$(dirname "$0")/abab_lib.sh"
_ebpf_tier() { python3 - <<'PY'
import json
try:
    c = json.load(open("/var/lib/observe/control.json")).get("ebpf") or {}
    import time
    print(c.get("tier") if c.get("until", 0) > time.time() else "")
except Exception:
    print("")
PY
}
abab_set_a()    { $OBS ebpf off >/dev/null; }
abab_set_b()    { $OBS ebpf on sample --for 10m >/dev/null; }
abab_verify_a() { [ -z "$(_ebpf_tier)" ]; }
abab_verify_b() { [ "$(_ebpf_tier)" = sample ]; }
abab_restore()  { $OBS ebpf off >/dev/null 2>&1; echo "ebpf=꺼짐"; }
abab_run
