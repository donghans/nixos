{
  pkgs,
  lib,
  config,
  ...
}:
with lib; let
  cfg = config.mods.gui;
in {
  imports = [
    ./home/_bind.nix
    ./home/_bind.hwctl.nix
    ./home/_ui.nix
    ./home/_ui.cursor.nix
    ./home/_ui.dark-mode.nix
    ./home/_ux.nix
    ./home/fuzzel.nix
    ./home/hyprlock.nix
    ./home/hyprpaper.nix
    ./home/kitty.nix
    ./home/mako.nix
    ./home/waybar.nix
    ./home/wl-clip.nix
  ];

  config = mkMerge [
    {
      _module.args = {
        hyprTerm = "${pkgs.kitty}/bin/kitty";
      };
    }
    (mkIf cfg.enable {
      wayland.windowManager.hyprland.enable = true;

      wayland.windowManager.hyprland.systemd = {
        enable = true;
        variables = ["--all"];
      };

      wayland.windowManager.hyprland.settings = {
        "$mainMod" = "SUPER";
      };

      home.packages = with pkgs; [
        nemo
      ];

      # == Wayland 환경 변수 ==
      home.sessionVariables = {
        ELECTRON_OZONE_PLATFORM_HINT = "auto";
      };

      # (참고: exec-once 위치)
      # - bluetooth        → mods/sys/services/bluetooth.nix
      # - networkmanager   → mods/sys/services/networkmanager.nix
      # - tailscale        → mods/sys/services/tailscale.nix
      # - hyprpaper        → home/hyprpaper.nix
      # - wl-clip-persist  → home/wl-clip.nix
      # - hyprpolkitagent  → core/polkit.nix
      # - fcitx5           → core/fcitx.nix
      # - waybar           → home/waybar.nix
    })
  ];
}
