{ pkgs, ... }: {
  imports = [ ./default.nix ];

  services.greetd.enable = true;

  services.greetd.settings.default_session = {
    command = "${pkgs.tuigreet}/bin/tuigreet --time --cmd 'uwsm start hyprland-uwsm.desktop'";
    user = "greeter";
  };

  systemd.services.greetd.serviceConfig = {
    Type = "idle";
    StandardInput = "tty";
    StandardOutput = "tty";
    StandardError = "journal"; # 로그 확인용
    TTYReset = true;
    TTYVHangup = true;
    TTYVTDisallocate = true;
  };

  programs.uwsm.enable = true; # uwsm 활성화 (Hyprland 세션 관리용)
  programs.hyprland.enable = true;
  programs.hyprland.withUWSM = true;

  security.polkit.enable = true;
  services.gnome.gnome-keyring.enable = true;

  # PAM을 통해 로그인 시 Keyring 자동 해제
  security.pam.services.login.enableGnomeKeyring = true;
  security.pam.services.greetd.enableGnomeKeyring = true;

  i18n.inputMethod = {
    enable = true;
    type = "fcitx5";

    fcitx5.waylandFrontend = true;
    fcitx5.addons = with pkgs; [
      fcitx5-hangul
      fcitx5-gtk
    ];
  };

  fonts = {
    packages = with pkgs; [
      nanum
      nanum-gothic-coding

      noto-fonts-cjk-sans    # 핵심: 한중일 Sans (추천)
      noto-fonts-cjk-serif   # 핵심: 한중일 Serif
      noto-fonts-color-emoji
    ];

    fontconfig.defaultFonts = {
      serif = [ "NanumMyeongjo" "Noto Serif CJK KR" ];
      sansSerif = [ "NanumGothic" "Noto Sans CJK KR" ];
      monospace = [ "NanumGothicCoding" ];
      emoji = [ "Noto Color Emoji" ];
    };
  };
}
