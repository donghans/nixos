#!/usr/bin/env python3
"""sbox 릴리스 데이터(releases.toml) 조회 도우미.

사용:
  release.py resolve <flavor> [<release>]   → 한 줄(단위 구분자 \\x1f 로 구분 — 탭은 read 가 빈 칸을 합쳐 버려서 쓰지 않는다): 코드네임 버전 상태 종료일 이미지 메모
  release.py list [<flavor>]                → 사람이 읽는 표

<release> 는 코드네임(trixie)이나 버전(13, 24.04)이다. 생략하면 그 flavor 의 default.
오류는 종료 코드 2 와 stderr 메시지로 알린다(sbox.sh 가 그대로 보여 준다).
"""
import sys
import tomllib
from pathlib import Path

DATA = Path(__file__).with_name("releases.toml")


def load():
    with DATA.open("rb") as f:
        return tomllib.load(f)


def fail(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)


def resolve(flavor, release):
    data = load()
    fl = data.get(flavor)
    if fl is None:
        fail(f"알 수 없는 flavor: {flavor} (데이터에 있는 것: {', '.join(sorted(data))})")
    rels = fl.get("release", {})
    if not release:
        release = fl.get("default", "")
    if release in rels:
        key = release
    else:
        hit = [k for k, v in rels.items() if v.get("version") == release]
        if not hit:
            fail(f"{flavor} 에 릴리스 {release!r} 가 없습니다 (있는 것: "
                 + ", ".join(f"{k}({v['version']})" for k, v in rels.items()) + ")")
        key = hit[0]
    r = rels[key]
    print("\x1f".join([key, r["version"], r["status"], r.get("eol", ""), r["image"], r.get("note", "")]))


def table(flavor):
    data = load()
    names = [flavor] if flavor else sorted(data)
    print(f"{'flavor':8s} {'release':10s} {'버전':6s} {'상태':10s} {'종료일':11s} 이미지")
    for fl in names:
        if fl not in data:
            fail(f"알 수 없는 flavor: {fl}")
        default = data[fl].get("default", "")
        for key, r in data[fl].get("release", {}).items():
            star = "*" if key == default else " "
            print(f"{fl:8s} {key + star:10s} {r['version']:6s} {r['status']:10s} {r.get('eol', '') or '-':11s} {r['image']}")
    print("(* = 기본값. eol 은 --legacy 필요, image 가 build: 인 것은 직접 빌드가 필요해 아직 만들 수 없음)")


def main(argv):
    if len(argv) >= 2 and argv[1] == "resolve" and len(argv) in (3, 4):
        resolve(argv[2], argv[3] if len(argv) == 4 else "")
    elif len(argv) >= 2 and argv[1] == "list" and len(argv) in (2, 3):
        table(argv[2] if len(argv) == 3 else "")
    else:
        fail(__doc__)


if __name__ == "__main__":
    main(sys.argv)
