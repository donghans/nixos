{pkgs, ...}: {
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
