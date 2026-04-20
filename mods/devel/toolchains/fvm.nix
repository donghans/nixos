{mkMod, ...}:
mkMod __curPos "Flutter Version Management" ({
  config,
  pkgs,
  ...
}: let
  fvmHome = "${config.home.homeDirectory}/.fvm"; # (목적: 빌드 타임에 절대 경로 확정 — $HOME 리터럴 문제 방지)
in {
  hm = {
    home.packages = [pkgs.fvm-wrapped];

    # 터미널 환경에서도 FVM_CACHE_PATH를 인식하도록 설정
    home.sessionVariables = {
      FVM_CACHE_PATH = fvmHome;
    };
  };
})
