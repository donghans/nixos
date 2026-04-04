{...}: {
  imports = [
    ./hardware/beelink-ser7-co.nix
    ./base/developer.nix
  ];

  # == Boot & Kernel ==
  boot = {
    consoleLogLevel = 3;
    kernelParams = [
      "amd_pstate=active" # (이유: 주전원 공급 시 성능 최적화)
      "nowatchdog" # (이유: 종료 시 Watchdog0 관련 메시지 방지)
      "loglevel=3" # (이유: 부팅 시 불필요한 펌웨어/로그 메시지 숨김)
      # [OPTIONAL] "amd_pstate=passive" (이유: USB-PD 전력 부족 시 강제 종료 방지)
    ];

    blacklistedKernelModules = ["sp5100_tco"]; # (이유: AMD 하드웨어 Watchdog 드라이버 차단)
    extraModprobeConfig = ''
      blacklist sp5100_tco
    '';
  };

  # (목적: 종료/재부팅 시 Watchdog 메시지 완전 차단)
  systemd.settings.Manager = {
    RuntimeWatchdogSec = "off";
    RebootWatchdogSec = "off";
    KExecWatchdogSec = "off";
  };

  fileSystems."/boot" = {
    device = "/dev/disk/by-uuid/C125-54BB";
    fsType = "vfat";
    options = ["fmask=0022" "dmask=0022"];
  };

  # == Services & Networking ==
  services = {
    auto-cpufreq = {
      enable = true;
      settings.charger = {
        governor = "performance";
        turbo = "always";
      };
    };

    # [OPTIONAL] USB-PD 전력공급 시 안정성 세팅
    # tlp = {
    #   enable = true;
    #   settings = {
    #     CPU_BOOST_ON_AC = 0;
    #     CPU_SCALING_GOVERNOR_ON_AC = "powersave";
    #     CPU_ENERGE_PERF_POLICY_ON_AC = "balance_performance";
    #     CPU_SCALING_MAX_FREQ_ON_AC = 3500000;
    #   };
    # };

    irqbalance.enable = true;
  };

  # (이유: Tailscale 등 이중 NAT 환경에서 Vivaldi 동기화 타임아웃 회피)
  networking.interfaces = {
    enp1s0.mtu = 1400; # 유선
    wlp2s0.mtu = 1400; # 무선
  };
}
