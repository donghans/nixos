# [working-refactor] 해당 구문은 before-refactor/lib/_base/default/_optimize.nix 에 있었음
# [working-refactor] 해당 구문은 after-refactor/... 로 들어가야 함
_: {
  # == Boot & System Logs / Watchdog ==
  boot = {
    consoleLogLevel = 3;
    kernelParams = [
      "nowatchdog"
      "loglevel=3"
      "pcie_aspm=off" # (이유: PCIe 전원 관리로 인한 인터럽트 지연 및 충돌 방지)
      "acpi_osi=Linux" # (이유: 리눅스 최적화 ACPI 설정 및 윈도우 전용 로직 우회)
    ];
    # AMD 및 Intel 하드웨어 Watchdog 드라이버 차단
    blacklistedKernelModules = ["sp5100_tco" "iTCO_wdt"];
  };

  # (목적: 종료/재부팅 시 Watchdog 메시지 완전 차단 및 지연 방지)
  systemd.settings.Manager = {
    RuntimeWatchdogSec = "off";
    RebootWatchdogSec = "off";
    KExecWatchdogSec = "off";
  };

  # (목적: 부팅 시 온라인 대기 비활성화로 부팅 속도 향상)
  systemd.services.NetworkManager-wait-online.enable = false;
  systemd.network.wait-online.enable = false;
}
