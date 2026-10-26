#!/usr/bin/env python3
"""diskbench — usageui 실시간 탭이 디스크 사용률(%)의 분모로 쓸 **순차 읽기·쓰기 실측**(짧은 벤치마크).

왜 실측인가: 제조사 표기 성능은 장치가 알려 주지 않고(모델명만 알려 줌), 표로 박아 넣으면 틀리거나 낡는다. 이 시스템의 파일시스템·암호화·연결 상태에서 실제로 내는 속도를 재서 기준으로 삼는다.
- 사용자가 확인한 뒤에만 돈다(usageui 의 `d` 키 → 확인 대화상자). 홈 아래 `~/.cache/observe-bench/` 에 임시 파일(기본 1 GiB)을 쓰고 읽고 지운다. 몇 초 걸리고 그동안 다른 측정에 영향을 준다.
- 측정 대상은 **그 임시 파일이 놓인 디스크**(루트·홈이 있는 디스크, LUKS·dm 은 아래 장치로 따라 내려감). 다른 디스크는 건드리지 않는다.
- 방식: 무작위 데이터를 1 MiB 블록으로 O_DIRECT 로 쓰고(fsync) → 다시 O_DIRECT 로 읽는다. O_DIRECT 를 못 쓰는 파일시스템이면 fadvise 로 캐시를 버리고 읽는다(결과에 direct=false 로 남음).
- 한계: 짧은 순차 측정이라 SLC 캐시가 찬 뒤의 지속 쓰기 속도·4K 랜덤은 재지 않는다 — 「이 시스템이 순차로 낼 수 있는 최고치」에 가깝다. 결과는 `~/.local/state/observe/disk-bench.json`.
- 거부: 여유 공간 부족(임시 파일 2배 + 1 GiB), I/O 압박(PSI io some avg10 ≥ 20%) 중.
네트워크는 재지 않는다: 상대 서버(iperf 등) 없이는 재는 것이 의미가 없고, 링크 속도는 하드웨어(sysfs·nmcli)가 직접 알려 준다.
사용: python3 diskbench.py [--size MiB] [--json]
"""
from __future__ import annotations

import errno
import json
import mmap
import os
import shutil
import sys
import time

BLOCK = 1 << 20
MAX_PHASE_S = 8.0


def state_path():
    base = os.environ.get("OBSERVE_STATE_DIR") or os.path.join(os.path.expanduser("~"), ".local", "state", "observe")
    return os.path.join(base, "disk-bench.json")


def load():
    try:
        with open(state_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(res):
    p = state_path()
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    os.replace(tmp, p)


def mount_source(path):
    """path 가 속한 마운트의 소스 장치 이름(예: nvme0n1p2) 또는 None — btrfs 처럼 st_dev 가 가상 번호(sysfs 에 없음)일 때 /proc/self/mountinfo 로 찾는다."""
    best = None
    try:
        for line in open("/proc/self/mountinfo"):
            f = line.split()
            mp, i = f[4], f.index("-")
            if (path == mp or path.startswith(mp.rstrip("/") + "/")) and (not best or len(mp) > len(best[0])):
                best = (mp, f[i + 2])
    except (OSError, ValueError, IndexError):
        return None
    if best and best[1].startswith("/dev/"):
        return os.path.basename(os.path.realpath(best[1]))
    return None


def whole_disks(path):
    """path 가 놓인 파일시스템 아래의 **전체 디스크** 이름 집합(파티션은 부모로, dm·LUKS 는 slaves 를 따라 내려감). loop·zram·ram·가상(tmpfs 등)은 빈 집합."""
    out, seen = set(), set()

    def walk(name):
        if name in seen or not os.path.isdir(f"/sys/class/block/{name}"):
            return
        seen.add(name)
        d = f"/sys/class/block/{name}"
        slaves = os.path.join(d, "slaves")
        if os.path.isdir(slaves) and os.listdir(slaves):
            for sl in os.listdir(slaves):
                walk(sl)
        elif os.path.exists(os.path.join(d, "partition")):
            walk(os.path.basename(os.path.dirname(os.path.realpath(d))))
        elif not name.startswith(("loop", "ram", "zram")):
            out.add(name)
    try:
        st = os.stat(path).st_dev
        link = f"/sys/dev/block/{os.major(st)}:{os.minor(st)}"
        name = os.path.basename(os.path.realpath(link)) if os.path.exists(link) else mount_source(path)
    except OSError:
        name = None
    if name:
        walk(name)
    return out


def bench_dir():
    return os.path.join(os.path.expanduser("~"), ".cache", "observe-bench")


def _io_pressure():
    try:
        for line in open("/proc/pressure/io"):
            if line.startswith("some"):
                return float(line.split("avg10=")[1].split()[0])
    except (OSError, IndexError, ValueError):
        pass
    return 0.0


def bench_file(directory, size_mib=1024, max_s=MAX_PHASE_S):
    """directory 에 임시 파일을 만들어 순차 쓰기·읽기 속도(바이트/초)를 잰다. 반환 dict(read, write, direct, size) — 실패는 dict(error=문구). 임시 파일은 항상 지운다."""
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as e:
        return dict(error=f"{directory} 를 만들 수 없다: {e.strerror or e}")
    path = os.path.join(directory, f"bench-{os.getpid()}.tmp")
    size = size_mib * (1 << 20)
    buf = mmap.mmap(-1, BLOCK)              # 페이지 정렬 버퍼(O_DIRECT 요구)
    buf.write(os.urandom(BLOCK))
    direct = True
    try:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_DIRECT, 0o600)
        except OSError as e:
            if e.errno != errno.EINVAL:
                raise
            direct = False
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            t0, done = time.monotonic(), 0
            while done < size and time.monotonic() - t0 < max_s:
                done += os.write(fd, buf)
            os.fsync(fd)
            wt = time.monotonic() - t0
        finally:
            os.close(fd)
        if not done or wt <= 0:
            return dict(error="쓰기 결과가 비었다")
        fd = os.open(path, os.O_RDONLY | (os.O_DIRECT if direct else 0))
        try:
            if not direct:
                os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
            t0, got = time.monotonic(), 0
            while got < done and time.monotonic() - t0 < max_s:
                n = os.readv(fd, [buf])
                if n <= 0:
                    break
                got += n
            rt = time.monotonic() - t0
        finally:
            os.close(fd)
        if not got or rt <= 0:
            return dict(error="읽기 결과가 비었다")
        return dict(read=got / rt, write=done / wt, direct=direct, size=done)
    except OSError as e:
        return dict(error=f"{e.strerror or e}")
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def run(size_mib=1024, directory=None, models=None):
    """확인을 받은 뒤 호출. 결과를 `disk-bench.json` 에 장치별로 저장하고 {장치: 결과} 를 돌려준다. 거부·실패는 {"error": 문구}.
    models: {장치: 모델명} (저장용, 선택)."""
    d = directory or bench_dir()
    try:
        os.makedirs(d, exist_ok=True)
        free = shutil.disk_usage(d).free
    except OSError as e:
        return dict(error=f"{d} 를 쓸 수 없다: {e.strerror or e}")
    if free < size_mib * (1 << 20) * 2 + (1 << 30):
        return dict(error=f"여유 공간이 부족({free / (1 << 30):.1f} GiB) — 임시 파일 {size_mib} MiB 의 2배 + 1 GiB 가 필요")
    psi = _io_pressure()
    if psi >= 20.0:
        return dict(error=f"지금 I/O 압박이 높다(PSI io some avg10 {psi:.0f}%) — 한가할 때 다시")
    disks = whole_disks(d)
    if not disks:
        return dict(error="임시 파일이 놓인 디스크를 알 수 없다(tmpfs 이거나 가상 장치)")
    r = bench_file(d, size_mib)
    if "error" in r:
        return r
    res = load()
    for disk in sorted(disks):
        res[disk] = dict(read=r["read"], write=r["write"], direct=r["direct"], size=r["size"], at=time.time(), dir=d, model=(models or {}).get(disk, ""),
                         shared=len(disks) > 1)
    save(res)
    return {disk: res[disk] for disk in disks}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size", type=int, default=1024, help="임시 파일 크기(MiB)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    out = run(a.size)
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    elif "error" in out:
        sys.exit(f"diskbench: {out['error']}")
    else:
        for k, v in out.items():
            print(f"{k}: 읽기 {v['read'] / 1e6:,.0f} MB/s · 쓰기 {v['write'] / 1e6:,.0f} MB/s ({'O_DIRECT' if v['direct'] else '캐시 우회 불가 — 읽기는 fadvise'}, {v['size'] >> 20} MiB)")
    return 0 if "error" not in out else 1


if __name__ == "__main__":
    sys.exit(main())
