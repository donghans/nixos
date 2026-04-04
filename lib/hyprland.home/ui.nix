{
  pkgs,
  lib,
  ...
}: {
  wayland.windowManager.hyprland.settings = {
    monitor = lib.mkDefault [",preferred,auto,1"];

    general = {
      gaps_in = 0;
      gaps_out = 0;
      border_size = 3;
      "col.active_border" = "rgba(33ccffee)";
      "col.inactive_border" = "rgba(595959aa)";
      resize_on_border = false;
      allow_tearing = false;
      layout = "dwindle";
    };

    dwindle = {
      pseudotile = true;
      preserve_split = true;
    };

    decoration = {
      rounding = 0;
      active_opacity = 1.0;
      inactive_opacity = 0.75;
      shadow.enabled = false;
      blur.enabled = false;
    };

    animations.enabled = "no";

    misc = {
      force_default_wallpaper = -1;
      disable_hyprland_logo = false;
      always_follow_on_dnd = true;
      focus_on_activate = true;
    };

    exec-once = [
      "hyprctl setcursor Bibata-Modern-Ice 24"
    ];
  };

  # 테마 설정 (다크모드 선호)
  home.pointerCursor = {
    gtk.enable = true;

    # x11.enable = true; # XWayland 앱들을 위해 필요할 수 있습니다.
    package = pkgs.bibata-cursors; # 추천하는 깔끔한 커서 테마
    name = "Bibata-Modern-Ice";
    size = 24;
  };

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
    cursorTheme = {
      name = "Bibata-Modern-Ice";
      package = pkgs.bibata-cursors;
    };

    # GTK4 앱들이 다크모드를 인식하게 만드는 핵심 설정
    gtk3.extraConfig.gtk-application-prefer-dark-theme = 1;
    gtk4.extraConfig.gtk-application-prefer-dark-theme = 1;
  };

  qt = {
    enable = true;
    platformTheme.name = "gtk"; # GTK 설정을 따라감
    # style.name = "adwaita-dark";
    # platformTheme.name = "qt5ct"; # 여기서 선언하면 sessionVariables를 알아서 세팅합니다.
  };

  dconf.settings = {
    "org/gnome/desktop/interface" = {
      color-scheme = "prefer-dark"; # 시스템 전역 다크모드 선호 신호
    };
  };
}
