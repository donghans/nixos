{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  config,
  pkgs,
  lib,
  ...
}: {
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
      wayland.windowManager.hyprland.package = pkgs.hyprland;
      wayland.windowManager.hyprland.configType = "lua";

      wayland.windowManager.hyprland.systemd = {
        enable = false;
        variables = ["--all"];
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
})
