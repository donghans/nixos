{
  pkgs,
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.gui;
in {
  config = mkIf cfg.enable (mkMerge [
    # == NixOS: Polkit 서비스 + GNOME Keyring ==
    (optionalAttrs isNixOS {
      security = {
        polkit.enable = true;
        # (목적: 로그인 시 GNOME Keyring 자동 해제 — login과 greetd 양쪽 필요)
        pam.services.login.enableGnomeKeyring = true;
        pam.services.greetd.enableGnomeKeyring = true;
      };
      services.gnome.gnome-keyring.enable = true;
    })

    # == Home Manager: Polkit 인증 에이전트 ==
    # (목적: Wayland 환경에서 권한 상승 다이얼로그 처리)
    (optionalAttrs (!isNixOS) {
      wayland.windowManager.hyprland.settings.exec-once = mkOrder 100 [
        "uwsm app -- ${pkgs.hyprpolkitagent}/libexec/hyprpolkitagent"
      ];
      home.packages = [pkgs.hyprpolkitagent];
    })
  ]);
}
