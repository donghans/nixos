{ pkgs, lib, metaConfig, ... }: {
  imports = [ ../../lib/hyprland.home.nix ];

  home.username = metaConfig.username;
  home.homeDirectory = "/home/${metaConfig.username}";

  home.packages = with pkgs; [
    bitwarden-desktop
    bitwarden-cli

    slack

    jetbrains.idea
    jetbrains.webstorm
    android-studio
    zed-editor

    antigravity
    jdk21

    nodejs_20
    python311
    nodePackages.yarn
    flutter
  ];

  programs.git.enable = true;
  programs.git.settings.user.name  = metaConfig.gitName;
  programs.git.settings.user.email = metaConfig.gitEmail;

  wayland.windowManager.hyprland.settings = {
    monitor = lib.mkForce [
      "eDP-1,2560x1600@60,auto,1" # 2560x1600@165, 60?
      "DP-2,preferred,auto-up,1"
    ];

    input = {
      # 1. 마우스 기본 속도 (-1.0 ~ 1.0, 0이 기본값)
      sensitivity = lib.mkForce 1;

      # 2. 마우스 가속 프로필
      # "flat"으로 설정하면 가속이 꺼지고 일정한 속도로 움직입니다 (개발자분들이 선호함)
      # "adaptive"가 기본 가속 모드입니다.
      accel_profile = "adaptive";

      touchpad = {
        # 기타 유용한 설정들
        natural_scroll = true;
        tap-to-click = true;
        disable_while_typing = true;
      };
    };
  };
}
