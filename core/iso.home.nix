{
  pkgs,
  lib,
  metaConfig,
  ...
}: {
  imports = [./lib/hyprland.home.nix];

  home.username = "nixos";
  home.homeDirectory = "/home/nixos";

  home.packages = with pkgs; [
    zed-editor
  ];

  programs.git.enable = true;
  programs.git.settings.user.name = metaConfig.gitName;
  programs.git.settings.user.email = metaConfig.gitEmail;

  wayland.windowManager.hyprland.settings = {
    input = {
      # 1. 마우스 기본 속도 (-1.0 ~ 1.0, 0이 기본값)
      sensitivity = lib.mkForce 1;

      # 2. 마우스 가속 프로필
      # "flat"으로 설정하면 가속이 꺼지고 일정한 속도로 움직입니다 (개발자분들이 선호함)
      # "adaptive"가 기본 가속 모드입니다.
      accel_profile = "adaptive";
    };
  };
}
