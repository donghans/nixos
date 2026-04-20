{mkMod, ...}:
# __curPos가 mods/devel.nix에서 평가되므로 경로가 "mods.devel"로 정확히 생성됨
# 하위 모듈들이 mkModOf "mods.devel"로 cascade를 직접 처리하므로 bodyFn 불필요
mkMod __curPos "Master switch for developer workshop" (_: {})
