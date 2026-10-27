# mods/_experiments — 수동 진단·실험 도구

Nix 모듈이 **설치하지 않고** 필요할 때 손으로 돌리는 도구를 둔다(`_` 접두 폴더라 모듈로 자동 로드되지 않음).
- `hypr-nested/` 중첩 Hyprland 로 설정 시험, `input-diagnostics/` 키 입력 점검(`key_probe.py`)·터치 기록 분석(`touch_trace.py`), `media-benchmark/` 미디어 프로그램 비교 측정
- `power-ab/` 전력 시험에서 쓴 일회성 스크립트(`power_ab.py` 실행기는 `mods/_tools/observe/power-ab/`)

승격 기준: Nix 가 설치하거나 반복해서 쓰게 되면 `mods/_tools/<카테고리>/` 로 옮긴다. 쓰임이 끝나면 지운다.
시험이 있는 도구(`input-diagnostics`)는 `mods/_tools/run-tests.sh` 가 함께 돌린다.
