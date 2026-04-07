{
  pkgs,
  lib,
  config,
  ...
}:
with lib; let
  cfg = config.mods.gui;
in {
  imports = [
    ./home/_bind.nix
    ./home/_bind.hwctl.nix
    ./home/_session.nix
    ./home/_ui.nix
    ./home/_ux.nix
    ./home/fuzzel.nix
    ./home/hyprlock.nix
    ./home/kitty.nix
    ./home/mako.nix
    ./home/waybar.nix
  ];

  config = mkMerge [
    {
      _module.args = {
        hyprTerm = "${pkgs.kitty}/bin/kitty";
      };
    }
    (mkIf cfg.enable {
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

      services.cliphist.enable = true;
    })
  ];
}
