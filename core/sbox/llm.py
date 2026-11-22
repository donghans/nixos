#!/usr/bin/env python3
"""sbox LLM 에이전트 정의(core/sbox/llm.toml) 조회 — sbox.sh 가 호출한다.
  llm.py list                 정의된 에이전트와 설명
  llm.py get AGENT FIELD      필드 값(문자열이면 그대로, 목록이면 공백으로 이어서). 없으면 종료코드 1
"""
import os
import sys
import tomllib

PATH = os.environ.get("SBOX_LLM_CATALOG", os.path.join(os.path.dirname(os.path.abspath(__file__)), "llm.toml"))


def load():
    with open(PATH, "rb") as f:
        return tomllib.load(f)


def main(a):
    d = load()
    if a[:1] == ["list"]:
        for k, v in d.items():
            print(f"{k}\t{v.get('desc', '')}")
    elif len(a) == 3 and a[0] == "get":
        if a[1] not in d:
            print(f"알 수 없는 에이전트: {a[1]} (정의된 것: {', '.join(d)} — 추가 방법은 core/sbox/llm.toml 머리말)", file=sys.stderr)
            sys.exit(1)
        v = d[a[1]].get(a[2])
        if v is None:
            print(f"{a[1]} 정의에 {a[2]} 가 없습니다", file=sys.stderr)
            sys.exit(1)
        print(" ".join(v) if isinstance(v, list) else v)
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main(sys.argv[1:])
