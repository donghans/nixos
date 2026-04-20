{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  pkgs,
  lib,
  ...
}: {
  os = {
    security = {
      polkit.enable = true;
      # (목적: 로그인 시 GNOME Keyring 자동 해제 — login과 greetd 양쪽 필요)
      pam.services.login.enableGnomeKeyring = true;
      pam.services.greetd.enableGnomeKeyring = true;
    };
    services.gnome.gnome-keyring.enable = true;
  };
  hm = {
    # (목적: Wayland 환경에서 권한 상승 다이얼로그 처리)
    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 100 [
      "uwsm app -- ${pkgs.hyprpolkitagent}/libexec/hyprpolkitagent"
    ];
    home.packages = [pkgs.hyprpolkitagent];
  };
})
