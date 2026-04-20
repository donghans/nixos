{mkMod, ...}: let
  base = mkMod __curPos null ({
    config,
    pkgs,
    lib,
    ...
  }: let
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
    os = lib.mkIf config.mods.gui.enable {
      # (목적: Wayland/GPU 가속을 위한 그래픽 드라이버 활성화)
      hardware.graphics.enable = true;
      hardware.graphics.enable32Bit = pkgs.stdenv.hostPlatform.isx86_64;

      programs = {
        uwsm.enable = true;
        hyprland.enable = true;
        hyprland.withUWSM = true;
      };

      # greeter.nix에 uwsm 세션 커맨드 주입
      mods.gui.base.greeter.sessionCmd = "uwsm start hyprland-uwsm.desktop";

      # (참고: services.blueman.enable은 mods.sys.services.bluetooth.nix에서 조건부 처리)
    };
    hm = lib.mkMerge [
      {
        _module.args = {
          hyprTerm = "${pkgs.kitty}/bin/kitty";
        };
      }
      (lib.mkIf config.mods.gui.enable {
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
        # - hyprpaper        → hyprpaper.nix
        # - wl-clip-persist  → wl-clip.nix
        # - hyprpolkitagent  → polkit.nix
        # - fcitx5           → fcitx.nix
        # - waybar           → waybar.nix
      })
    ];
  });
in {
  inherit (base) imports;
}
