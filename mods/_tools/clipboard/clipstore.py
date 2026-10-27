#!/usr/bin/env python3
"""clipstore — `wl-paste --watch` 용 저장 래퍼

stdin 으로 들어온 클립보드 내용을 cliphist 에 그대로 저장(기존 동작)하고,
저장이 끝난 뒤 부가 정보(시각·출처 앱·복사 횟수)를 clipmeta 에 기록한다.
부가 정보 기록이 실패해도 이력 저장 자체에는 영향이 없다.
"""
import sys

import clipmeta


def main() -> int:
    data = sys.stdin.buffer.read()
    if not data:
        return 0
    result = clipmeta.cliphist("store", data=data)
    if result.returncode != 0:
        sys.stderr.write(result.stderr.decode("utf-8", "replace"))
        return result.returncode
    try:
        clipmeta.record(data)
    except Exception as exc:  # noqa: BLE001 — 부가 정보 때문에 수집이 멈추면 안 됨
        sys.stderr.write(f"clipstore: 부가 정보 기록 실패: {exc!r}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
