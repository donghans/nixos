# [working-refactor] 해당 구문은 before-refactor/lib/_base/hyprland.nix 에 있었음
# [working-refactor] 해당 구문은 after-refactor/... 로 들어가야 함
{pkgs, ...}: {
  # [working-refactor] 해당 파일은 실제 /tmp/nixos-build/<경로> 로 이동 후 nhw에 의해 임시 경로에서 실행됩니다.
  imports = [
    ../../sys/base/os.nix
    ./os/custom-notify-logger.nix
  ];

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
