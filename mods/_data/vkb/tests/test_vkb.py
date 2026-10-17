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
check("크기 이름: 360=medium, 300=custom", vkb.size_name(360) == "medium" and vkb.size_name(300) == "custom")

# 자세 연동
check("laptop 이면 숨김", vkb.desired_visibility("laptop") is False)
check("tent/tablet 이면 보임", vkb.desired_visibility("tent") and vkb.desired_visibility("tablet"))
print(f"\nvkb {ok} 통과 / {bad} 실패")
sys.exit(1 if bad else 0)
