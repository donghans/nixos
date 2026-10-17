#!/usr/bin/env python3
"""가짜 hyprctl: 실측한 모니터와 실제 Hyprland 의 관찰된 동작을 흉내 낸다.
 - 미러는 mirror = "" 로만 풀리고, 꺼진 모니터는 disabled = false 로만 켜진다(필드를 빼면 상태가 그대로 남음)
 - 내장 패널은 48Hz 미만의 사용자 지정 주사율을 거부(현재 모드 유지), 외장은 모두 받아들임
 - 창 목록/이동과 이벤트 순서(move, disable)를 기록 (창을 먼저 옮긴 뒤 모니터를 끄는지 검증용)"""
import json, os, re, sys
S = os.environ["FAKE_STATE"]
EDP_MODES = ["2560x1600@165.04Hz", "2560x1600@60.04Hz"]
DP_MODES = ["3840x2560@60.00Hz", "3840x2560@50.00Hz", "3840x2160@60.00Hz", "2560x1440@59.95Hz", "1920x1080@60.00Hz",
            "1920x1080@59.94Hz", "1280x720@60.00Hz", "1024x768@60.00Hz", "800x600@60.32Hz", "640x480@60.00Hz"]
def baseline():
    return [
        dict(id=0, name="eDP-1", description="AU Optronics 0xD298", width=2560, height=1600, refreshRate=60.043, x=0, y=0, scale=1.0,
             transform=0, disabled=False, mirrorOf="none", availableModes=EDP_MODES),
        dict(id=1, name="DP-4", description="MNT 2728UDP4K 000000000000", width=3840, height=2560, refreshRate=60.0, x=0, y=-2560, scale=1.0,
             transform=0, disabled=False, mirrorOf="none", availableModes=DP_MODES),
    ]
def load():
    try: return json.load(open(S))
    except Exception: return baseline()
def save(d): json.dump(d, open(S, "w"))
LOG, WIN = S + ".events", S + ".windows"
def log(x): open(LOG, "a").write(x + "\n")
def windows():
    try: return json.load(open(WIN))
    except Exception: return []
def check_overlap(d):
    """켜져 있고 미러가 아닌 모니터끼리 겹치면 기록 (실제 Hyprland 는 이때 화면에 경고 말풍선을 띄움)"""
    live = [m for m in d if not m["disabled"] and m["mirrorOf"] == "none"]
    for i, a in enumerate(live):
        for b in live[i + 1:]:
            def lg(m):  # 회전 90/270 이면 논리 가로세로가 바뀜(실제 Hyprland 와 같음)
                w, h = round(m["width"] / m["scale"]), round(m["height"] / m["scale"])
                return (h, w) if m.get("transform", 0) % 2 == 1 else (w, h)
            ra = (a["x"], a["y"], *lg(a))
            rb = (b["x"], b["y"], *lg(b))
            if ra[0] < rb[0] + rb[2] and rb[0] < ra[0] + ra[2] and ra[1] < rb[1] + rb[3] and rb[1] < ra[1] + ra[3]:
                log(f"OVERLAP {a['name']} {b['name']}")
def field(code, k):
    m = re.search(r'\b%s\s*=\s*("([^"]*)"|[A-Za-z0-9_.\-]+)' % k, code)
    if not m: return None
    return m.group(2) if m.group(2) is not None else m.group(1)
def main(a):
    d = load()
    if a[:2] == ["clients", "-j"]: print(json.dumps(windows())); return
    if a[0] == "dispatch":
        m = re.search(r'monitor = "([^"]+)".*address:(0x[0-9a-f]+)', a[1])
        if m:
            tgt = next(x for x in d if x["name"] == m.group(1)); ws = windows()
            for w in ws:
                if w["address"] == m.group(2): w["monitor"] = tgt["id"]
            json.dump(ws, open(WIN, "w")); log("move " + m.group(2) + " -> " + m.group(1))
        print("ok"); return
    if a[:2] == ["monitors", "all"] or a[:1] == ["monitors"]:
        print(json.dumps(d if a[:2] == ["monitors", "all"] else [m for m in d if not m["disabled"]])); return
    if a[0] == "reload": save(baseline()); print("ok"); return
    if a[0] == "eval":
        code = a[1]; name = field(code, "output")
        m = next((x for x in d if x["name"] == name), None)
        if m is None: print("ok"); return
        if field(code, "disabled") == "true": m["disabled"] = True; log("disable " + name); check_overlap(d); save(d); print("ok"); return
        log(f"rule {name} pos={field(code, 'position')} disabled={field(code, 'disabled')}")
        if field(code, "disabled") == "false": m["disabled"] = False
        mir = field(code, "mirror")
        if mir is not None:
            m["mirrorOf"] = "none" if mir == "" else str(next(x["id"] for x in d if x["name"] == mir))
        mode = field(code, "mode")
        if mode:
            if mode == "preferred": mode = m["availableModes"][0]
            mm = re.match(r"(\d+)x(\d+)@([\d.]+)", mode); w, h, hz = int(mm[1]), int(mm[2]), float(mm[3])
            listed = [x for x in m["availableModes"] if x.startswith(f"{w}x{h}@") and abs(float(x.split("@")[1][:-2]) - hz) < 0.5]
            if listed: m["width"], m["height"], m["refreshRate"] = w, h, float(listed[0].split("@")[1][:-2])
            elif m["name"].startswith("eDP") and hz < 48: pass
            else: m["width"], m["height"], m["refreshRate"] = w, h, hz
        pos = field(code, "position")
        if pos and pos != "auto": px, py = pos.split("x"); m["x"], m["y"] = int(px), int(py)
        sc = field(code, "scale")
        if sc: m["scale"] = float(sc)
        tr = field(code, "transform")
        if tr is not None: m["transform"] = int(tr)
        check_overlap(d); save(d); print("ok"); return
    print("ok")
main(sys.argv[1:])
