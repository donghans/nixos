#!/usr/bin/env python3
"""media-bench — 이미지/영상/오디오 프로그램의 "창이 뜨기까지의 시간"과 "시작 직후 2초 동안의 CPU 시간"을 비교한다.

사용:  python3 bench.py [횟수] [--only 이름,이름]       예) python3 bench.py 5   /   python3 bench.py 1 --only imv,swayimg
 - 필요한 프로그램은 nix 로 임시로 내려받고(시스템에 설치하지 않음) 시험용 파일은 ffmpeg 로 합성해서 만든다.
 - Hyprland 에서만 동작(hyprctl clients 로 새 창을 감지). 측정 중 창이 화면에 잠깐씩 뜬다.
 - 측정 환경에 따라 값이 크게 달라진다: 전원(AC/배터리, TLP 의 CPU 상한), 터보, 다른 작업. 같은 조건에서 상대 비교로만 볼 것.
 - "창이 뜬 시점" 은 첫 화면/첫 소리가 나는 시점과 다르다.
"""
import json, os, shutil, signal, statistics as st, subprocess, sys, tempfile, time

WORK = os.path.join(tempfile.gettempdir(), "media-bench")
HZ = os.sysconf("SC_CLK_TCK")


def nix_path(attr: str) -> str:
    out = subprocess.run(["nix", "build", "--no-link", "--print-out-paths", f"nixpkgs#{attr}"], capture_output=True, text=True).stdout.split()
    # 다중 출력(bin, man, dev ...)이면 실행 파일이 실제로 들어 있는 출력을 고름
    return next((o for o in out if os.path.exists(f"{o}/bin/{attr}")), out[0])


def make_samples() -> dict:
    os.makedirs(WORK, exist_ok=True)
    f = {k: os.path.join(WORK, v) for k, v in dict(img="img.png", img4k="img-4k.jpg", vid="vid.mp4", flac="aud.flac").items()}
    if all(os.path.exists(p) for p in f.values()):
        return f
    sh = (f"ffmpeg -loglevel error -y -f lavfi -i testsrc2=size=1920x1080:rate=1 -frames:v 1 {f['img']} && "
          f"ffmpeg -loglevel error -y -f lavfi -i testsrc2=size=3840x2160:rate=1 -frames:v 1 -q:v 3 {f['img4k']} && "
          f"ffmpeg -loglevel error -y -f lavfi -i testsrc2=duration=6:size=1920x1080:rate=30 -f lavfi -i sine=frequency=440:duration=6 "
          f"-c:v libx264 -pix_fmt yuv420p -c:a aac -shortest {f['vid']} && "
          f"ffmpeg -loglevel error -y -f lavfi -i sine=frequency=440:duration=6 -c:a flac {f['flac']}")
    subprocess.run(["nix", "shell", "nixpkgs#ffmpeg-headless", "-c", "sh", "-c", sh], check=True)
    return f


def clients() -> dict:
    r = subprocess.run(["hyprctl", "clients", "-j"], capture_output=True, text=True)
    try:
        return {c["address"]: c for c in json.loads(r.stdout)}
    except ValueError:
        return {}


def tree_cpu(root: int) -> float:
    ppid, cpu = {}, {}
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                f = open(f"/proc/{d}/stat").read().rsplit(")", 1)[1].split()
                ppid[int(d)] = int(f[1]); cpu[int(d)] = (int(f[11]) + int(f[12])) / HZ
            except OSError:
                pass
    kids, stack = {root}, [root]
    while stack:
        x = stack.pop()
        for k, v in ppid.items():
            if v == x and k not in kids:
                kids.add(k); stack.append(k)
    return sum(cpu.get(k, 0) for k in kids)


def one(cmd: list) -> tuple:
    before = set(clients())
    t0 = time.time()
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, start_new_session=True)
    tw = cls = None
    while time.time() - t0 < 20:
        time.sleep(0.02)
        new = [c for a, c in clients().items() if a not in before]
        if new:
            tw, cls = time.time() - t0, new[0]["class"]
            break
    cpu = None
    if tw is not None:
        time.sleep(max(0, 2.0 - (time.time() - t0 - tw)) + 0.5)  # 창이 뜬 뒤 2초까지
        cpu = tree_cpu(p.pid)
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        p.wait(timeout=3)
    except Exception:
        pass
    for _ in range(40):  # 창이 사라지고 D-Bus 이름이 풀릴 때까지(GApplication 은 단일 인스턴스)
        if not [a for a in clients() if a not in before]:
            break
        time.sleep(0.1)
    time.sleep(0.8)
    return tw, cpu, cls


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    runs = int(args[0]) if args and args[0].isdigit() else 5
    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    f = make_samples()
    names = ["mpv", "celluloid", "vlc", "amberol", "loupe", "imv", "swayimg"]
    P = {n: nix_path(n) for n in names if not only or n.split("(")[0] in only or n in only}
    b = lambda n: f"{P[n]}/bin/{n}"
    cases = [
        ("이미지 PNG 1080p", "loupe", lambda: [b("loupe"), f["img"]]),
        ("이미지 PNG 1080p", "imv", lambda: [b("imv"), f["img"]]),
        ("이미지 PNG 1080p", "swayimg", lambda: [b("swayimg"), f["img"]]),
        ("이미지 JPG 4K", "loupe", lambda: [b("loupe"), f["img4k"]]),
        ("이미지 JPG 4K", "imv", lambda: [b("imv"), f["img4k"]]),
        ("이미지 JPG 4K", "swayimg", lambda: [b("swayimg"), f["img4k"]]),
        ("영상 1080p H.264", "mpv", lambda: [b("mpv"), "--no-config", f["vid"]]),
        ("영상 1080p H.264", "mpv(VA-API)", lambda: [b("mpv"), "--no-config", "--hwdec=vaapi", f["vid"]]),
        ("영상 1080p H.264", "celluloid", lambda: [b("celluloid"), f["vid"]]),
        ("영상 1080p H.264", "vlc", lambda: [b("vlc"), "--no-metadata-network-access", f["vid"]]),
        ("오디오 FLAC", "mpv", lambda: [b("mpv"), "--no-config", "--force-window=yes", f["flac"]]),
        ("오디오 FLAC", "celluloid", lambda: [b("celluloid"), f["flac"]]),
        ("오디오 FLAC", "vlc", lambda: [b("vlc"), "--no-metadata-network-access", f["flac"]]),
        ("오디오 FLAC", "amberol", lambda: [b("amberol"), f["flac"]]),
    ]
    cases = [c for c in cases if c[1].split("(")[0] in P]
    res = {(g, n): [] for g, n, _ in cases}
    for i in range(runs):
        for g, n, mk in cases:
            tw, cpu, cls = one(mk())
            res[(g, n)].append((tw, cpu))
            print(f"run{i+1} {g} / {n}: 창 {tw if tw is None else round(tw*1000)}ms cpu {cpu} class={cls}", flush=True)
    print("\n=== 요약 (중앙값, 창이 뜬 시도만)")
    for g in dict.fromkeys(g for g, _, _ in cases):
        print(f"[{g}]")
        for gg, n, _ in cases:
            if gg != g:
                continue
            ok = [(t, c) for t, c in res[(g, n)] if t is not None]
            if not ok:
                print(f"  {n:12s} 창이 뜨지 않음"); continue
            ts = [t * 1000 for t, _ in ok]; cs = [c * 1000 for _, c in ok if c is not None]
            print(f"  {n:12s} 창 {st.median(ts):6.0f}ms ({min(ts):.0f}~{max(ts):.0f})   CPU(2초) {st.median(cs):6.0f}ms   [{len(ok)}/{len(res[(g, n)])}회]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
