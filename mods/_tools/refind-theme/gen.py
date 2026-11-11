#!/usr/bin/env python3
"""rEFInd 테마 에셋 생성기 (plan refind-theme R1). 결정적: 같은 입력·같은 파라미터면 같은 PNG.

  gen.py SRC_THEME_DIR OUT_DIR [--pitch 3] [--small 72]

SRC_THEME_DIR = refind-theme-regular(icons/128-48 로 큰/작은 구분, icons/512-192 를 고해상도 원본으로 읽는다).
OUT_DIR 에 icons/*.png, bg_black.png, selection-{big,small}.png, theme.conf 를 쓴다.
 - 배경: 단색 #000000 (그림 없음 — Windows 체인 잔상 방지).
 - 아이콘: 원본을 목표 크기(큰 128 · 작은 --small)로 줄인 뒤 pitch 격자로 나눠 **점 하나**로 바꾼다.
   모든 아이콘(큰·작은·기능)이 같은 pitch → 화면 픽셀 기준으로 점 간격이 같다(터미널 위에 뜬 점 그래픽).
   점 색 = 칸 평균 색(여러 색 유지, 검정 위에서 보이게 35% 밝힘), 점 반지름 = 칸의 밝기에 비례(R_LO~R_HI × pitch; 최대가 0.5 미만이라 점 사이에 항상 틈이 남음) →
   채워진 모양 안의 어두운 세부(터미널 `>`, 시계 바늘, 펭귄 눈)가 작은 점으로 남아 의미가 읽힌다.
 - 선택 영역: 반투명 흰색(채움 α48·테두리 α120) → 검정 위 회색 사각. 크기 = 아이콘 + 16.
"""
import argparse, os, sys
from PIL import Image, ImageDraw

R_HI, R_LO, THR, SS, BRIGHT = 0.44, 0.20, 0.55, 8, 0.35

def dotify(img, size, pitch):
    img = img.convert("RGBA").resize((size, size), Image.LANCZOS)
    g = size // pitch
    cell = img.convert("RGBa").resize((g, g), Image.BOX).convert("RGBA")   # 칸 평균(알파 가중)
    px = cell.load()
    ls = sorted((0.2126 * px[x, y][0] + 0.7152 * px[x, y][1] + 0.0722 * px[x, y][2]) / 255.0
                for y in range(g) for x in range(g) if px[x, y][3] > 60)
    ref = max(0.25, ls[int(len(ls) * 0.9)]) if ls else 1.0                 # 아이콘마다 상위 10% 밝기를 기준으로 정규화
    out = Image.new("RGBA", (size * SS, size * SS), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    for gy in range(g):
        for gx in range(g):
            r, gg, b, a = px[gx, gy]
            c = a / 255.0
            if c < 0.12:
                continue
            lum = (0.2126 * r + 0.7152 * gg + 0.0722 * b) / 255.0
            rad = R_LO + (R_HI - R_LO) * min(1.0, lum / ref)
            if c < THR:
                rad *= 0.7                                                  # 가장자리 칸은 작게
            col = tuple(min(255, int(v * (1 - BRIGHT) + 255 * BRIGHT)) for v in (r, gg, b))
            cx, cy, R = (gx + 0.5) * pitch * SS, (gy + 0.5) * pitch * SS, rad * pitch * SS
            d.ellipse((cx - R, cy - R, cx + R, cy + R), fill=col + (255,))
    return out.resize((size, size), Image.LANCZOS)

def selection(size):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle((0, 0, size - 1, size - 1), radius=max(4, size // 16),
                                         fill=(255, 255, 255, 48), outline=(255, 255, 255, 120), width=1)
    return im

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--pitch", type=int, default=3)
    ap.add_argument("--small", type=int, default=72)
    a = ap.parse_args()
    base = os.path.join(a.src, "icons")
    odir = os.path.join(a.out, "icons")
    os.makedirs(odir, exist_ok=True)
    n = 0
    for name in sorted(os.listdir(os.path.join(base, "128-48"))):
        if not name.endswith(".png") or name.startswith(("bg", "selection")):
            continue
        small = Image.open(os.path.join(base, "128-48", name)).size[0] < 100
        src = Image.open(os.path.join(base, "512-192", name))
        dotify(src, a.small if small else 128, a.pitch).save(os.path.join(odir, name)); n += 1
    Image.new("RGBA", (32, 32), (0, 0, 0, 255)).save(os.path.join(odir, "bg_black.png"))
    selection(128 + 16).save(os.path.join(odir, "selection-big.png"))
    selection(a.small + 16).save(os.path.join(odir, "selection-small.png"))
    open(os.path.join(a.out, "theme.conf"), "w").write(
        f"icons_dir themes/refind-dot/icons\nbig_icon_size 128\nsmall_icon_size {a.small}\n"
        "banner themes/refind-dot/icons/bg_black.png\nbanner_scale fillscreen\n"
        "selection_big themes/refind-dot/icons/selection-big.png\nselection_small themes/refind-dot/icons/selection-small.png\n"
        "font themes/refind-theme-regular/fonts/source-code-pro-extralight-14.png\n")
    print(f"icons dotified: {n}, out: {a.out}")

if __name__ == "__main__":
    sys.exit(main())
