{
  pkgs,
  lib,
  config,
  ...
}:
with lib; let
  cfg = config.mods.gui;
  # Hyprland 0.52.1 pipe FD 누수 버그픽스 (v0.54.0에서 수정됨)
  # 수정 커밋: c92fb5e8 (orphan transfers), b8fc0def (INCR), 1761909b (pipe check)
  # TODO: nixpkgs가 Hyprland 0.54.0+ 를 안정 채널에 포함하면 아래 커스텀 fetch 제거 가능
  nixpkgs-for-hyprland-bugfix =
    import (builtins.fetchTarball {
      url = "https://github.com/NixOS/nixpkgs/archive/38eccbbf297c.tar.gz";
      sha256 = "1w5zkgqhgi9b9zwsaz64vlhf9rcb5dmjz0mb05vgx7l5ycb851dj";
    }) {
      localSystem = pkgs.stdenv.hostPlatform.system;
      config.allowUnfree = true;
    };
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
    ./home/satty.nix
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
      wayland.windowManager.hyprland.package = nixpkgs-for-hyprland-bugfix.hyprland;

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
