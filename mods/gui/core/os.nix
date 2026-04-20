{mkMod, ...}:
mkMod __curPos null ({
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

    # (참고: services.blueman.enable은 mods.sys.services.bluetooth.nix에서 조건부 처리)
  };
})
