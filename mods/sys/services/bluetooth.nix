{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.bluetooth;
in
  if isNixOS
  then {
    config = mkIf cfg.enable {
      hardware.bluetooth = {
        enable = true;
        powerOnBoot = true;
      };
      # GUI 활성화 시 Blueman GUI 블루투스 관리 도구 활성화
      services.blueman.enable = config.mods.gui.enable;
    };
  }
  else {
    # HM 사이드: GUI 활성화 시 Hyprland 세션에서 블루투스 언블록 및 전원 ON
    config = mkIf (cfg.enable && config.mods.gui.enable) {
      wayland.windowManager.hyprland.settings.exec-once = [
        "rfkill unblock bluetooth && bluetoothctl power on"
      ];
    };
  }
