{ pkgs, config, ... }: {
  _module.args = {
    hyprTerm = "${pkgs.kitty}/bin/kitty";
    notifyLog = "${config.home.homeDirectory}/.local/share/notify_logs/history.log";
  };

  imports = [
    ./default.home.nix
    ./hyprland.home/fuzzel.nix
    ./hyprland.home/hyprland.nix
      ./hyprland.home/hyprland/bind.nix
      ./hyprland.home/hyprland/init.nix
      ./hyprland.home/hyprland/ui.nix
    ./hyprland.home/kitty.nix
    ./hyprland.home/mako.nix
    ./hyprland.home/waybar.nix
  ];

  home.packages = with pkgs; [
    hyprpolkitagent

    qgnomeplatform
    qgnomeplatform-qt6

    xdg-desktop-portal-gtk
    xdg-desktop-portal-hyprland

    nemo

    vivaldi
    vivaldi-ffmpeg-codecs
  ];

  programs = {
    bash.enable = true;
  };

  services.cliphist.enable = true;

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

    theme = { name = "Adwaita-dark"; package = pkgs.gnome-themes-extra; };
    iconTheme = { name = "Papirus-Dark"; package = pkgs.papirus-icon-theme; };
    cursorTheme = { name = "Bibata-Modern-Ice"; package = pkgs.bibata-cursors; };

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

  xdg.configFile."xdg-desktop-portal/portals.conf".text = ''
    [preferred]
    default=gtk;hyprland
    org.freedesktop.impl.portal.FileChooser=gtk
    org.freedesktop.impl.portal.Settings=gtk
  '';
}
