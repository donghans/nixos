{
  config,
  lib,
  ...
}:
with lib; let
  isRpi = config.workspace.type == "rpi";
  isVm = config.mods.sys.services.incus-guest.enable;
  isServer = config.mods.sys.server.enable;
  isLaptop = config.workspace.type == "laptop";

  # (목적: RPi(ARM)과 VM 내부에서는 TLP가 무의미하거나 오작동할 수 있으므로 제외)
  enableTlp = !isRpi && !isVm;

  laptopSettings = {
    CPU_SCALING_GOVERNOR_ON_AC = "balanced";
    CPU_ENERGY_PERF_POLICY_ON_AC = "balance_performance";
    CPU_MAX_PERF_ON_AC = 100;

    CPU_SCALING_GOVERNOR_ON_BAT = "powersave";
    CPU_ENERGY_PERF_POLICY_ON_BAT = "power";
    CPU_MAX_PERF_ON_BAT = 50;

    USB_AUTOSUSPEND = 0;
    USB_EXCLUDE_PHONE = 1;
    SATA_LINKPWR_ON_BAT = "med_power_with_dipm";

    RUNTIME_PM_ON_AC = "auto";
    RUNTIME_PM_ON_BAT = "auto";

    WIFI_PWR_ON_AC = "off";
    WIFI_PWR_ON_BAT = "off";

    DEVICES_TO_DISABLE_ON_BAT_NOT_IN_USE = "";
    MAX_LOST_WORK_SECS_ON_BAT = 60;
    MAX_LOST_WORK_SECS_ON_AC = 15;
  };

  desktopSettings = {
    CPU_SCALING_GOVERNOR_ON_AC = "performance";
    CPU_ENERGY_PERF_POLICY_ON_AC = "balance_performance";
    WIFI_PWR_ON_AC = "off";
    RUNTIME_PM_ON_AC = "auto";
    MAX_LOST_WORK_SECS_ON_AC = 15;
  };

  serverSettings = {
    # (목적: 서버는 터보만 끄고 나머지는 TLP 기본값으로 성능 유지)
    CPU_BOOST_ON_AC = 0;
  };

  tlpSettings =
    if isServer
    then serverSettings
    else if isLaptop
    then laptopSettings
    else desktopSettings;
in
  mkIf enableTlp {
    services.tlp = {
      enable = true;
      settings = tlpSettings;
    };
  }
