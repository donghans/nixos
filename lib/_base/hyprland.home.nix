{
  pkgs,
  lib,
  ...
}: {
  _module.args = {
    hyprTerm = "${pkgs.kitty}/bin/kitty";
  };

  imports = [
    ./default.home.nix
    ./hyprland.home/_bind.nix
    ./hyprland.home/_bind.hwctl.nix
    ./hyprland.home/_session.nix
    ./hyprland.home/_ui.nix
    ./hyprland.home/_ux.nix
    ./hyprland.home/fuzzel.nix
    ./hyprland.home/hyprlock.nix
    ./hyprland.home/kitty.nix
    ./hyprland.home/mako.nix
    ./hyprland.home/vivaldi.nix
    ./hyprland.home/waybar.nix
  ];

  wayland.windowManager.hyprland.enable = true;

  wayland.windowManager.hyprland.systemd = {
    enable = true;
    variables = ["--all"];
  };

  wayland.windowManager.hyprland.settings = {
    "$mainMod" = "SUPER";

    ### INPUT ###
    input = {
      kb_layout = "kr";
      kb_options = "korean:ralt_hangul,korean:rctrl_hanja";

      follow_mouse = 1;

      # 1. 마우스 기본 속도 (-1.0 ~ 1.0, 0이 기본값)
      sensitivity = lib.mkForce 1;

      # 2. 마우스 가속 프로필
      # "flat"으로 설정하면 가속이 꺼지고 일정한 속도로 움직입니다 (개발자분들이 선호함)
      # "adaptive"가 기본 가속 모드입니다.
      accel_profile = "adaptive";

      touchpad = {
        natural_scroll = true;
      };
    };

    # [OPTIONAL] 특정 하드웨어 전용 설정
    # device = [ { name = "epic-mouse-v1"; sensitivity = -0.5; } ];
  };

  home.packages = with pkgs; [
    hyprpolkitagent

    qgnomeplatform
    qgnomeplatform-qt6

    xdg-desktop-portal-gtk
    xdg-desktop-portal-hyprland
    xdg-utils

    nemo

    wl-clip-persist
  ];

  xdg = {
    portal.enable = true;
    portal.extraPortals = with pkgs; [
      xdg-desktop-portal-hyprland
      xdg-desktop-portal-gtk
    ];

    portal.config.common.default = ["hyprland" "gtk"];

    mimeApps.enable = true;
  };

  programs = {
    gh.enable = true;
  };

  services.cliphist.enable = true;
}
