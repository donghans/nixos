{
  config,
  lib,
  ...
}: {
  # == Boot & System Logs / Watchdog ==
  boot = {
    consoleLogLevel = 3;
    kernelParams =
      [
        "nowatchdog"
        "loglevel=3"
        "pcie_aspm=off" # (이유: PCIe 전원 관리로 인한 인터럽트 지연 및 충돌 방지)
        "acpi_osi=Linux" # (이유: 리눅스 최적화 ACPI 설정 및 윈도우 전용 로직 우회)
      ]
      ++ lib.optionals config.mods.sys.serverMode.enable [
        "intel_iommu=on" # 가상화 하드웨어 가속
        "iommu=pt"
      ];
    # AMD 및 Intel 하드웨어 Watchdog 드라이버 차단
    blacklistedKernelModules = ["sp5100_tco" "iTCO_wdt"];
  };

  # (목적: 서버용 고성능 네트워크 및 파일 시스템 최적화)
  boot.kernel.sysctl = lib.mkIf config.mods.sys.serverMode.enable {
    # TCP stack optimization for server
    "net.core.somaxconn" = 4096;
    "net.ipv4.tcp_fastopen" = 3;
    "net.ipv4.tcp_max_syn_backlog" = 8192;
    "net.ipv4.tcp_slow_start_after_idle" = 0;
    "net.core.netdev_max_backlog" = 10000;

    # File handle limits
    "fs.file-max" = 1000000;
    "fs.inotify.max_user_watches" = 524288;
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
