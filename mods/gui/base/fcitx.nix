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

    # (목적: 파일 선택창(xdg-desktop-portal-gtk, GTK3)의 한글 입력)
    # 전역 GTK_IM_MODULE이 공백이면 GTK3 포털 프로세스가 fcitx와 연결되지 않아 한글이 입력되지 않음
    # 포털 서비스에만 fcitx를 지정 (GTK4 앱은 전역 설정대로 text-input-v3 사용)
    xdg.configFile."systemd/user/xdg-desktop-portal-gtk.service.d/fcitx.conf".text = ''
      [Service]
      Environment=GTK_IM_MODULE=fcitx
    '';
  };
})
