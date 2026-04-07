{
  pkgs,
  lib,
  config,
  ...
}:
with lib; let
  cfg = config.mods.gui;
in {
  config = mkIf cfg.enable {
    # (목적: XDG Portal 경로를 시스템 PATH에 노출 — Wayland 포털 탐색에 필요)
    environment.pathsToLink = ["/share/applications" "/share/xdg-desktop-portal"];

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
      StandardError = "journal"; # (이유: stderr는 저널로 분리하여 TTY 출력 오염 방지)
      TTYReset = true;
      TTYVHangup = true;
      TTYVTDisallocate = true;
    };

    programs = {
      uwsm.enable = true;
      hyprland.enable = true;
      hyprland.withUWSM = true;
    };

    security = {
      polkit.enable = true;
      # (목적: 로그인 시 GNOME Keyring 자동 해제 — login과 greetd 양쪽 필요)
      pam.services.login.enableGnomeKeyring = true;
      pam.services.greetd.enableGnomeKeyring = true;
    };
    services.gnome.gnome-keyring.enable = true;

    # (목적: GUI 환경의 Bluetooth 트레이 관리자 — CLI에서는 bluetoothctl로 충분)
    services.blueman.enable = true;

    # == Input Method ==
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
}
