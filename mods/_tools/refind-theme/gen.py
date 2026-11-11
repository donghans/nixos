#!/usr/bin/env python3
"""rEFInd 테마 에셋 생성기 (plan refind-theme R1). 결정적: 같은 입력·같은 파라미터면 같은 PNG.

  gen.py SRC_THEME_DIR OUT_DIR [--pitch 4] [--color RRGGBB] [--mode mono|tint]

SRC_THEME_DIR = refind-theme-regular (icons/128-48 를 읽는다). OUT_DIR/icons 에 아이콘, bg_black.png, selection-{big,small}.png 를 쓴다.
 - 배경: 1x1 #000000 (banner_scale fillscreen 으로 늘림; 그림 없음 — Windows 체인 잔상 방지).
 - 아이콘: 원본 128px RGBA 를 pitch 격자로 나눠 칸의 (불투명도 x 밝기)로 원형 점 반지름을 정한 도트 매트릭스.
   mono = 한 색(--color), tint = 칸의 평균 색을 점 색으로.
 - 선택 영역: 반투명 흰색 사각(채움 알파 40, 테두리 알파 110), big 144 / small 64.
"""
import argparse, os, sys
from PIL import Image, ImageDraw

def dotify(img, pitch, mode, color, ss=4):
    img = img.convert("RGBA")
    w, h = img.size
    out = Image.new("RGBA", (w * ss, h * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(out)
    for gy in range(0, h, pitch):
        for gx in range(0, w, pitch):
            cell = img.crop((gx, gy, gx + pitch, gy + pitch))
            px = list(cell.getdata())
            a = sum(p[3] for p in px) / (255.0 * len(px))
            if a < 0.08:
                continue
            lum = sum((0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2]) * p[3] for p in px) / (255.0 * sum(p[3] for p in px) or 1)
            v = a * (0.35 + 0.65 * lum)          # 어두운 칸도 작은 점은 남긴다
            r = (pitch / 2.0) * min(1.0, 0.25 + 0.85 * v) * ss
            if mode == "tint":
                tw = sum(p[3] for p in px) or 1
                col = tuple(int(sum(p[i] * p[3] for p in px) / tw) for i in range(3))
                col = tuple(min(255, int(c * 0.6 + 255 * 0.4)) for c in col)   # 검정 위에서 보이게 밝힘
            else:
                col = color
            cx, cy = (gx + pitch / 2.0) * ss, (gy + pitch / 2.0) * ss
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col + (int(255 * min(1.0, 0.45 + a)),))
    return out.resize((w, h), Image.LANCZOS)

def selection(size, fill_a=40, border_a=110):
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=max(4, size // 16), fill=(255, 255, 255, fill_a), outline=(255, 255, 255, border_a), width=1)
    return im

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--pitch", type=int, default=4)
    ap.add_argument("--color", default="9fe8b0")
    ap.add_argument("--mode", choices=["mono", "tint"], default="mono")
    a = ap.parse_args()
    color = tuple(int(a.color[i:i + 2], 16) for i in (0, 2, 4))
    src = os.path.join(a.src, "icons", "128-48")
    odir = os.path.join(a.out, "icons")
    os.makedirs(odir, exist_ok=True)
    n = 0
    for name in sorted(os.listdir(src)):
        if not name.endswith(".png") or name.startswith(("bg", "selection")):
            continue
        im = Image.open(os.path.join(src, name))
        if im.size[0] < 100:       # 화살표 등 작은 UI 이미지는 그대로
            im.convert("RGBA").save(os.path.join(odir, name), optimize=False); continue
        dotify(im, a.pitch, a.mode, color).save(os.path.join(odir, name), optimize=False); n += 1
    Image.new("RGBA", (1, 1), (0, 0, 0, 255)).save(os.path.join(odir, "bg_black.png"))
    selection(144).save(os.path.join(odir, "selection-big.png"))
    selection(64).save(os.path.join(odir, "selection-small.png"))
    print(f"icons dotified: {n}, out: {a.out}")

if __name__ == "__main__":
    sys.exit(main())
