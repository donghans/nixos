#!/usr/bin/env python3
"""displayctl — Hyprland 화면 관리 CLI의 진입점(얇은 파일). 본체는 같은 디렉터리의 패키지 `dispctl/` (구성은 dispctl/__init__.py 참고).

이 파일이 있는 이유: `import displayctl as dc`(displayui, 시험)와 `python3 displayctl.py …`(시험의 서브프로세스, Nix 래퍼)가
단일 파일일 때와 똑같이 동작하게 하는 호환 껍데기다. 이름은 패키지에서 그대로 가져온다.
(Nix 가 @hyprctl@, @notify_send@ 자리표시자를 dispctl/config.py 에서 실제 경로로 치환한다 — mods/gui/base/monitor-manager.nix)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))     # python -I 로 실행해도 옆의 dispctl 패키지를 찾게
import dispctl as _pkg                                              # noqa: E402

globals().update({k: v for k, v in vars(_pkg).items() if not k.startswith("__")})   # 이전 이름 그대로(밑줄 이름 포함)

if __name__ == "__main__":
    sys.exit(_pkg.cli.main(sys.argv[1:]))
