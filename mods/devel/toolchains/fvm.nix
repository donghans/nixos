{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  modCfg = config.mods.devel.fvm;
  fvmHome = "${config.home.homeDirectory}/.fvm"; # (목적: 빌드 타임에 절대 경로 확정 — $HOME 리터럴 문제 방지)
in
  {
    options.mods.devel.fvm.enable = mkEnableOption "Flutter Version Management";
  }
  // (
    if isNixOS
    then {}
    else {
      config = mkIf modCfg.enable {
        home.packages = [pkgs.fvm-wrapped];

        # 터미널 환경에서도 FVM_CACHE_PATH를 인식하도록 설정
        home.sessionVariables = {
          FVM_CACHE_PATH = fvmHome;
        };
      };
    }
  )
