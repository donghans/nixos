#!/bin/sh
# 가짜 brightnessctl: `-q set N` 만 지원. FAKE_BL(백라이트 디렉터리)의 brightness 에 쓴다.
[ "$2" = set ] && echo "$3" > "$FAKE_BL/brightness"
