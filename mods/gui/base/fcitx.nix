{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  pkgs,
  lib,
  ...
}: {
  os = {
    i18n.inputMethod = {
      enable = true;
      type = "fcitx5";
      fcitx5.waylandFrontend = true;
      fcitx5.addons = with pkgs; [
        fcitx5-hangul
        fcitx5-gtk
      ];
    };
  };
  hm = {
    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 500 [
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
  };
})
