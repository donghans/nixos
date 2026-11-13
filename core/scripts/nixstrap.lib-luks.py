#!/usr/bin/env python3
"""nixstrap.lib-luks.py — nixstrap 의 LUKS 복구 암호 생성·검사 헬퍼 (오프라인)

서브커맨드:
  gen [단어수]      → 복구 암호(소문자 영어 단어, 공백 1칸)를 stdout 에 출력 (기본 8, 최소 6)
  bits [단어수]     → 그 단어 수의 엔트로피(비트, 소수 1자리)
  normalize         → stdin 한 줄을 정규화(소문자·공백 1칸·앞뒤 공백 제거)해 stdout 에 출력
  words             → 번호를 붙여 표시할 수 있게 stdin 암호를 `N. 단어` 줄로 출력
  check-wordlist    → 단어 목록 무결성 검사(7776개·중복 없음·sha256); 실패하면 종료 코드 1

단어 목록: EFF large wordlist (https://www.eff.org/dice, CC BY 3.0 US — © Electronic Frontier Foundation).
암호는 인자로 받지 않는다(ps 에 보이므로). 로그·파일에 쓰지 않는다.
"""
import hashlib
import math
import os
import secrets
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
WORDLIST = os.environ.get("NIXSTRAP_WORDLIST") or os.path.join(HERE, "nixstrap.data-eff-large.txt")
WORDLIST_SHA256 = "addd35536511597a02fa0a9ff1e5284677b8883b83e986e43f15a3db996b903e"
WORDLIST_COUNT = 7776
DEFAULT_WORDS = 8
MIN_WORDS = 6


def _read_bytes(path=None):
    with open(path or WORDLIST, "rb") as f:
        return f.read()


def load_words(path=None, verify=True):
    """단어 목록을 읽는다. verify 면 무결성(sha256·개수·중복·빈 단어)을 검사해 어긋나면 ValueError."""
    raw = _read_bytes(path)
    if verify and hashlib.sha256(raw).hexdigest() != WORDLIST_SHA256:
        raise ValueError("단어 목록 sha256 불일치")
    words = []
    for line in raw.decode("utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) != 2 or not parts[1]:
            raise ValueError(f"단어 목록 줄 형식 오류: {line!r}")
        words.append(parts[1])
    if verify:
        if len(words) != WORDLIST_COUNT:
            raise ValueError(f"단어 수 {len(words)} != {WORDLIST_COUNT}")
        if len(set(words)) != len(words):
            raise ValueError("단어 중복")
    return words


def entropy_bits(n_words, list_size=WORDLIST_COUNT):
    return n_words * math.log2(list_size)


def generate(n_words=DEFAULT_WORDS, words=None, randbelow=secrets.randbelow):
    if n_words < MIN_WORDS:
        raise ValueError(f"단어 {MIN_WORDS}개 미만은 거부한다")
    words = words if words is not None else load_words()
    return " ".join(words[randbelow(len(words))] for _ in range(n_words))


def normalize(s):
    return " ".join(s.lower().split())


def _cmd_gen(args):
    n = int(args[0]) if args else DEFAULT_WORDS
    sys.stdout.write(generate(n) + "\n")


def _cmd_bits(args):
    n = int(args[0]) if args else DEFAULT_WORDS
    print(f"{entropy_bits(n):.1f}")


def _cmd_normalize(_args):
    sys.stdout.write(normalize(sys.stdin.readline()) + "\n")


def _cmd_words(_args):
    for i, w in enumerate(normalize(sys.stdin.readline()).split(), 1):
        print(f"{i}. {w}")


def _cmd_check(_args):
    try:
        w = load_words()
    except Exception as e:  # noqa: BLE001
        print(f"FAIL {e}", file=sys.stderr)
        sys.exit(1)
    print(f"ok {len(w)}")


COMMANDS = {"gen": _cmd_gen, "bits": _cmd_bits, "normalize": _cmd_normalize,
            "words": _cmd_words, "check-wordlist": _cmd_check}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    try:
        COMMANDS[sys.argv[1]](sys.argv[2:])
    except ValueError as e:
        print(f"오류: {e}", file=sys.stderr)
        sys.exit(1)
