{pkgs, ...}: {
  imports = [./default.nix];

  services.greetd = {
    enable = true;
    settings.default_session = {
      command = "${pkgs.tuigreet}/bin/tuigreet --time --cmd 'uwsm start hyprland-uwsm.desktop'";
      user = "greeter";
    };
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

  programs = {
    uwsm.enable = true; # uwsm 활성화 (Hyprland 세션 관리용)
    hyprland.enable = true;
    hyprland.withUWSM = true;
  };

  security = {
    polkit.enable = true;
    # PAM을 통해 로그인 시 Keyring 자동 해제
    pam.services.login.enableGnomeKeyring = true;
    pam.services.greetd.enableGnomeKeyring = true;
  };
  services.gnome.gnome-keyring.enable = true;

  # == Input Method & Fonts ==
  i18n.inputMethod = {
    enable = true;
    type = "fcitx5";
    fcitx5.waylandFrontend = true;
    fcitx5.addons = with pkgs; [
      fcitx5-hangul
      fcitx5-gtk
    ];
  };
}
