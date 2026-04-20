{mkMod, ...}:
mkMod __curPos "Bluetooth support" ({
  cfg,
  config,
  lib,
  ...
}: {
  os = {
    hardware.bluetooth = {
      enable = true;
      powerOnBoot = true;
    };
    # GUI 활성화 시 Blueman GUI 블루투스 관리 도구 활성화
    services.blueman.enable = config.mods.gui.enable;
  };
  hm = lib.mkIf config.mods.gui.enable {
    # HM 사이드: GUI 활성화 시 Hyprland 세션에서 블루투스 언블록 및 전원 ON
    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 100 [
      "rfkill unblock bluetooth && bluetoothctl power on"
    ];
  };
})
