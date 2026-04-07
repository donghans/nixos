{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.bluetooth;
in {
  options.mods.sys.services.bluetooth.enable = mkEnableOption "Bluetooth support";
  config = mkIf cfg.enable (
    if isNixOS
    then {
      hardware.bluetooth = {
        enable = true;
        powerOnBoot = true;
      };
      # GUI 활성화 시 Blueman GUI 블루투스 관리 도구 활성화
      services.blueman.enable = config.mods.gui.enable;
    }
    else
      mkIf config.mods.gui.enable {
        # HM 사이드: GUI 활성화 시 Hyprland 세션에서 블루투스 언블록 및 전원 ON
        wayland.windowManager.hyprland.settings.exec-once = [
          "rfkill unblock bluetooth && bluetoothctl power on"
        ];
      }
  );
}
