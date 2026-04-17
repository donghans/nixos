{
  pkgs,
  lib,
  config,
  ...
}:
# (목적: mods.gui.enable이 false인 서버/헤드리스 환경에서 dconf 접근 시도를 차단)
# (이유: gtk.enable=true와 dconf.settings는 HM 활성화 시 dconf 데몬에 접속하려 하는데,
#        GUI 없는 환경에서는 dconf 서비스가 없어 home-manager 서비스가 실패함)
lib.mkIf config.mods.gui.enable {
  # == GTK 다크모드 ==
  gtk = {
    enable = true;

    theme = {
      name = "Adwaita-dark";
      package = pkgs.gnome-themes-extra;
    };
    iconTheme = {
      name = "Papirus-Dark";
      package = pkgs.papirus-icon-theme;
    };

    # GTK4 앱들이 다크모드를 인식하게 만드는 핵심 설정
    gtk3.extraConfig.gtk-application-prefer-dark-theme = 1;
    gtk4.extraConfig.gtk-application-prefer-dark-theme = 1;
  };

  # == Qt 테마 ==
  qt = {
    enable = true;
    platformTheme.name = "gtk"; # GTK 설정을 따라감
  };

  # == 시스템 전역 다크모드 선호 신호 ==
  dconf.settings = {
    "org/gnome/desktop/interface" = {
      color-scheme = "prefer-dark";
    };
  };

  # == Qt/GTK 브릿지 패키지 ==
  # (목적: Qt5/Qt6 앱이 GTK 테마를 따르도록 하는 플랫폼 플러그인)
  home.packages = with pkgs; [
    qgnomeplatform
    qgnomeplatform-qt6
  ];

  # == 환경 변수 ==
  home.sessionVariables = {
    GTK_THEME = "Adwaita-dark";
    QT_QPA_PLATFORM = "wayland;xcb";
  };
}
