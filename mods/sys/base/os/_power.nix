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
    # AC: 응답성과 효율의 균형 / BAT: 최대 절전
    CPU_SCALING_GOVERNOR_ON_AC = "balanced";
    CPU_ENERGY_PERF_POLICY_ON_AC = "balance_performance";
    CPU_MAX_PERF_ON_AC = 100; # AC에서는 성능 제한 없음

    CPU_SCALING_GOVERNOR_ON_BAT = "powersave";
    CPU_ENERGY_PERF_POLICY_ON_BAT = "power";
    CPU_MAX_PERF_ON_BAT = 50; # 배터리에서 최대 클럭 50% 제한

    USB_AUTOSUSPEND = 0; # (이유: 자동 USB 절전 시 마우스·키보드 입력 끊김 방지)
    USB_EXCLUDE_PHONE = 1; # (이유: 폰 충전 중 절전 진입으로 인한 충전 중단 방지)
    SATA_LINKPWR_ON_BAT = "med_power_with_dipm"; # (이유: SSD 절전 + DIPM으로 링크 전력 절감)

    RUNTIME_PM_ON_AC = "auto"; # PCIe 디바이스 런타임 절전 (커널 드라이버 판단에 맡김)
    RUNTIME_PM_ON_BAT = "auto";

    WIFI_PWR_ON_AC = "off"; # (이유: Wi-Fi 절전 시 주기적 연결 끊김 방지)
    WIFI_PWR_ON_BAT = "off";

    DEVICES_TO_DISABLE_ON_BAT_NOT_IN_USE = ""; # (이유: 블루투스 등 자동 비활성화 방지)
    MAX_LOST_WORK_SECS_ON_BAT = 60; # 배터리: dirty page writeback 최대 지연 60s
    MAX_LOST_WORK_SECS_ON_AC = 15; # AC: dirty page writeback 최대 지연 15s
  };

  desktopSettings = {
    CPU_SCALING_GOVERNOR_ON_AC = "performance"; # 데스크탑은 항상 AC — 성능 우선
    CPU_ENERGY_PERF_POLICY_ON_AC = "balance_performance";
    WIFI_PWR_ON_AC = "off"; # (이유: Wi-Fi 절전 시 주기적 연결 끊김 방지)
    RUNTIME_PM_ON_AC = "auto"; # PCIe 디바이스 런타임 절전 (커널 드라이버 판단에 맡김)
    MAX_LOST_WORK_SECS_ON_AC = 15; # dirty page writeback 최대 지연 15s
  };

  serverSettings = {
    # (목적: 서버는 터보만 끄고 나머지는 TLP 기본값으로 성능 유지)
    # (이유: 터보 부스트는 순간 전력 급증으로 열 설계 한계를 넘길 수 있음)
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
