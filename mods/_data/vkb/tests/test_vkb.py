#!/usr/bin/env python3
"""vkb 순수 로직 시험: 창 맞춤 계획, 복원 계획, 크기 단계, 자세 연동 판정."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import vkb

ok = bad = 0
def check(name, cond, extra=""):
    global ok, bad
    if cond: ok += 1
    else: bad += 1; print("  FAIL", name, extra)

def win(addr, x, y, w, h, floating=True, hidden=False, fullscreen=0):
    return {"address": addr, "at": [x, y], "size": [w, h], "floating": floating, "hidden": hidden, "fullscreen": fullscreen}

KB = 1240   # 2560x1600 화면에서 키보드(높이 360) 윗면

# 맞춤 계획
p = vkb.fit_plan([win("0xa", 100, 100, 800, 600)], KB)
check("키보드 위에 있는 창은 그대로", p == {}, str(p))
p = vkb.fit_plan([win("0xb", 100, 700, 800, 700)], KB)         # 아래끝 1400 > 1240 → 높이 540 (>=260)
check("조금 가려지면 높이만 줄임", p == {"0xb": (100, 700, 800, 540)}, str(p))
p = vkb.fit_plan([win("0xc", 100, 1100, 800, 400)], KB)        # 높이를 140 으로 줄여야 → 260 미만이라 위로 이동
check("높이가 너무 작아지면 위로 옮김(높이는 min 이상 유지)", p == {"0xc": (100, 980, 800, 260)}, str(p))
p = vkb.fit_plan([win("0xd", 0, 27, 2554, 1570)], KB)          # 거의 전체 화면 크기 창
check("전체 크기 창은 높이를 줄여서 키보드 위에 맞춤", p == {"0xd": (0, 27, 2554, 1213)}, str(p))
check("타일(floating 아님) 창은 건드리지 않음(배타 영역으로 이미 줄어듦)", vkb.fit_plan([win("0xe", 0, 700, 800, 900, floating=False)], KB) == {})
check("숨김/전체화면 창은 건드리지 않음", vkb.fit_plan([win("0xf", 0, 1100, 800, 400, hidden=True), win("0xg", 0, 1100, 800, 400, fullscreen=2)], KB) == {})
p = vkb.fit_plan([win("0xh", 100, 1200, 500, 300)], 300)       # 아주 작은 화면(키보드 윗면 300): 창이 화면 밖으로 안 나감
check("작은 화면에서도 y>=0, 창이 키보드 위에 들어감", p["0xh"][1] >= 0 and p["0xh"][1] + p["0xh"][3] <= 300, str(p))

# 복원 계획
saved = {"0xb": {"orig": [100, 700, 800, 700], "fitted": [100, 700, 800, 540]},
         "0xc": {"orig": [100, 1100, 800, 400], "fitted": [100, 980, 800, 260]},
         "0xz": {"orig": [0, 0, 100, 100], "fitted": [0, 0, 100, 50]}}
cur = [win("0xb", 100, 700, 800, 540), win("0xc", 150, 900, 800, 260)]    # 0xc 는 사용자가 옮김, 0xz 는 닫힘
r = vkb.restore_plan(saved, cur)
check("맞춘 상태 그대로인 창만 원래 지오메트리로 복원", r == {"0xb": (100, 700, 800, 700)}, str(r))
check("사용자가 옮긴 창(0xc)은 복원하지 않음", "0xc" not in r)
check("닫힌 창은 무시", "0xz" not in r)

# 크기 단계
check("small 에서 down 은 그대로", vkb.next_size("small", "down") == "small")
check("medium 에서 up 은 large", vkb.next_size("medium", "up") == "large")
check("large 에서 up 은 그대로", vkb.next_size("large", "up") == "large")
check("모르는 값은 medium 취급", vkb.next_size("x", "up") == "large")

check("크기 순환 small→medium", vkb.cycle_size("small") == "medium")
check("크기 순환 large→small", vkb.cycle_size("large") == "small")
check("크기 이름: 10mm=medium, 9=custom, 이름은 그대로", vkb.size_name(10) == "medium" and vkb.size_name(9) == "custom" and vkb.size_name("large") == "large")
check("mm 변환: 이름/숫자/범위 밖", vkb.row_mm_of("small") == 8.0 and vkb.row_mm_of(11) == 11.0 and vkb.row_mm_of(99) == 30.0 and vkb.row_mm_of("x") == 10.0)

# 화면 물리 크기로 치수 계산(이 기기: 2560x1600, 340x220mm → 7.53px/mm)
G = {"w": 2560, "h": 1600, "mm_w": 340.0, "mm_h": 220.0}
L = vkb.compute_layout(10.0, 14.5, G)
check("medium: 가로 5줄 ≈ 376px, 세로 6줄 ≈ 452px", L["land"] == 376 and L["port"] == 452, str(L))
check("키보드 폭: 15키 × 16mm ≈ 1807px, 글자 18pt", vkb.compute_layout(10.0, 16.0, G)["width"] == 1807 and L["font_pt"] == 18, str(L))
H2 = vkb.compute_layout(10.0, 14.5, dict(G, mm_w=170.0, mm_h=110.0))
check("너무 커지면 화면 높이의 45% 로 제한", H2["land"] <= 1600 * 0.45 and H2["port"] <= 1600 * 0.45, str(H2))
check("폭은 화면 폭을 넘지 않음", vkb.compute_layout(30.0, 99.0, G)["width"] == 2560)
check("글자 크기 범위 12~32", vkb.compute_layout(4.0, 14.5, G)["font_pt"] >= 12 and vkb.compute_layout(30.0, 14.5, G)["font_pt"] <= 32)

# 자세 연동
check("laptop 이면 숨김", vkb.desired_visibility("laptop") is False)
check("tent/tablet 이면 보임", vkb.desired_visibility("tent") and vkb.desired_visibility("tablet"))
# ───── 배열 패치와 vkb.py 상수의 일치(두 곳에 따로 적힌 같은 지식이 어긋나면 키 폭/높이 계산이 틀어짐) ─────
# 패치는 바뀐 곳만 담고 있어서 원본 wvkbd 소스에 두 패치를 실제로 적용한 결과를 읽는다(원본: 환경변수 WVKBD_SRC, 없으면 `nix build nixpkgs#wvkbd.src`).
import re, shutil, subprocess, tempfile
WV = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "wvkbd")
src = os.environ.get("WVKBD_SRC")
if not src:
    r = subprocess.run(["nix", "build", "--no-link", "--print-out-paths", "nixpkgs#wvkbd.src"], capture_output=True, text=True)
    src = r.stdout.strip().splitlines()[-1] if r.returncode == 0 and r.stdout.strip() else None
if not src or not os.path.isdir(src):
    print("  SKIP 배열 패치 검사: wvkbd 원본 소스를 구하지 못함(WVKBD_SRC 로 지정 가능)")
else:
    tmp = tempfile.mkdtemp()
    shutil.copytree(src, tmp + "/b"); subprocess.run(["chmod", "-R", "u+w", tmp + "/b"])
    for name in ("float-mode.patch", "pc-layout.patch"):
        r = subprocess.run(["patch", "-p1", "-d", tmp + "/b", "-i", os.path.join(WV, name)], capture_output=True, text=True)
        check(f"{name} 이 원본 wvkbd 에 깔끔히 적용됨", r.returncode == 0 and "FAILED" not in r.stdout, r.stdout[-200:])
    text = open(tmp + "/b/layout.mobintl.h").read()
    body = text[text.index("static struct key keys_landscape[] = {"):]
    rows, cur = [], 0.0
    for l in body.splitlines()[1:]:
        m = re.match(r'\s*\{"(?:[^"\\]|\\.)*", "(?:[^"\\]|\\.)*", ([0-9.]+), (\w+)', l)
        if not m:
            continue
        if m[2] == "Last":
            break
        if m[2] == "EndRow":
            rows.append(cur); cur = 0.0
        else:
            cur += float(m[1])
    rows.append(cur)                                # 마지막 줄(Last 앞에 EndRow 가 없음)
    check("가로 배열 줄 수 == vkb.LAND_ROWS", len(rows) == vkb.LAND_ROWS, f"{len(rows)} != {vkb.LAND_ROWS}")
    check("가로 배열의 모든 줄 폭 합 == vkb.LAND_UNITS (키보드 폭 = 단위 × 키 폭 계산의 전제)", all(abs(r - vkb.LAND_UNITS) < 1e-6 for r in rows), str(rows))
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\nvkb {ok} 통과 / {bad} 실패")
sys.exit(1 if bad else 0)
