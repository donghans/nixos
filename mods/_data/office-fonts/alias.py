#!/usr/bin/env python3
"""폰트 별칭 생성: 원본 글꼴의 이름표(name 테이블)만 바꾼 복사본을 만든다. 글리프는 원본 그대로.

사용: alias.py <출력 디렉터리> "<별칭 패밀리 이름>=<원본 글꼴 파일>" ...

왜: ONLYOFFICE 는 문서가 지정한 글꼴이 설치돼 있지 않으면 자체 알고리즘으로 대체 글꼴을 고르는데(시스템 fontconfig 와 무관),
그 선택을 지정할 설정이 없다. 문서의 글꼴 이름과 정확히 같은 이름의 글꼴을 두면 그 글꼴을 쓰므로, 없는 이름(KoPub돋움체 등)에
Pretendard 같은 범용 글꼴을 같은 이름으로 연결한다.
 - Windows 플랫폼 이름표(영어/한국어)만 쓴다. Mac 이름표는 Mac Roman 으로 한글을 인코딩할 수 없어 저장이 실패하므로 제거.
 - 패밀리 이름 안에 굵기가 들어 있는 이름("KoPub돋움체 Bold")이라 스타일은 Regular 로 둔다(굵기는 글리프 자체).
"""
import os
import sys

from fontTools.ttLib import TTFont


def make(src, family, out):
    f = TTFont(src)
    name = f["name"]
    ps = "".join(c for c in family.replace(" ", "-") if c.isascii() and (c.isalnum() or c == "-")) or "Alias"
    for nid in (1, 2, 3, 4, 6, 16, 17, 21, 22, 25):
        name.removeNames(nameID=nid)
    for lid in (0x409, 0x412):
        name.setName(family, 1, 3, 1, lid)
        name.setName("Regular", 2, 3, 1, lid)
        name.setName(family + " Regular", 4, 3, 1, lid)
        name.setName("Alias-" + ps, 3, 3, 1, lid)
        name.setName("Alias-" + ps, 6, 3, 1, lid)
    f.save(out)


def main():
    outdir = sys.argv[1]
    os.makedirs(outdir, exist_ok=True)
    for i, spec in enumerate(sys.argv[2:]):
        family, src = spec.rsplit("=", 1)
        make(src, family, os.path.join(outdir, f"zz-alias-{i:02d}.otf"))


if __name__ == "__main__":
    main()
