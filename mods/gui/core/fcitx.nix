{
  pkgs,
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.gui;
in {
  config = mkIf cfg.enable (mkMerge [
    # == NixOS: 시스템 레벨 Fcitx5 설치 ==
    (optionalAttrs isNixOS {
      i18n.inputMethod = {
        enable = true;
        type = "fcitx5";
        fcitx5.waylandFrontend = true;
        fcitx5.addons = with pkgs; [
          fcitx5-hangul
          fcitx5-gtk
        ];
      };
    })

    # == Home Manager: 세션 실행 + 환경 변수 ==
    (optionalAttrs (!isNixOS) {
      wayland.windowManager.hyprland.settings.exec-once = mkOrder 500 [
        "uwsm app -- fcitx5"
      ];

      # (주의: GTK_IM_MODULE은 GTK4부터 공백 권장 — IBus/fcitx5-gtk 포털로 대체됨)
      home.sessionVariables = {
        GTK_IM_MODULE = "";
        QT_IM_MODULE = "fcitx";
        XMODIFIERS = "@im=fcitx";
        SDL_IM_MODULE = "fcitx";
        INPUT_METHOD = "fcitx";
      };
    })
  ]);
}
