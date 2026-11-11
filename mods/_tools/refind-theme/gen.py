#!/usr/bin/env python3
"""rEFInd 테마 변형 생성기 (plan refind-theme): 원본 refind-theme-regular 의 아이콘·글꼴은 그대로 쓰고 **배경과 선택 영역 색만** 바꾼다.

  gen.py SRC_THEME_DIR OUT_DIR [--sel-alpha 0.55]

SRC_THEME_DIR = ESP 의 refind-theme-regular. OUT_DIR(= ESP 의 themes/refind-black) 에 theme.conf, bg_black.png, selection-{big,small}.png 를 쓴다.
 - 배경: 32x32 단색 #000000 (그림 없음 — Windows 체인 잔상 방지). 원본 bg_dark.png 는 32x32 #222222 였다.
 - 선택 영역: 원본 selection_dark-*.png 의 **모양(알파 채널)을 그대로** 두고 색만 검정 → 흰색, 알파에 --sel-alpha 를 곱한다(0.55 → 검정 위 #464646). 테두리 등은 더하지 않는다.
 - 아이콘·글꼴은 원본 폴더를 가리킨다(복사 안 함). 점 그래픽 아이콘 시도(고해상도 원본→도트 변환)는 표현력이 부족해 기각 — 커밋 a680f2f 에 남아 있다.
"""
import argparse, os, sys
from PIL import Image

def recolor(path, k):
    a = Image.open(path).convert("RGBA").getchannel("A").point(lambda v: int(round(v * k)))
    out = Image.new("RGBA", a.size, (255, 255, 255, 0))
    out.putalpha(a)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("out")
    ap.add_argument("--sel-alpha", type=float, default=0.55)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    ic = os.path.join(a.src, "icons", "128-48")
    Image.new("RGBA", (32, 32), (0, 0, 0, 255)).save(os.path.join(a.out, "bg_black.png"))
    recolor(os.path.join(ic, "selection_dark-big.png"), a.sel_alpha).save(os.path.join(a.out, "selection-big.png"))
    recolor(os.path.join(ic, "selection_dark-small.png"), a.sel_alpha).save(os.path.join(a.out, "selection-small.png"))
    open(os.path.join(a.out, "theme.conf"), "w").write(
        "icons_dir themes/refind-theme-regular/icons/128-48\nbig_icon_size 128\nsmall_icon_size 48\n"
        "banner themes/refind-black/bg_black.png\nbanner_scale fillscreen\n"
        "selection_big themes/refind-black/selection-big.png\nselection_small themes/refind-black/selection-small.png\n"
        "font themes/refind-theme-regular/fonts/source-code-pro-extralight-14.png\n")
    print("ok:", a.out)

if __name__ == "__main__":
    sys.exit(main())
