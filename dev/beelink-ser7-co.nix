{ config, ... }: {
  imports = [
    ./hardware/beelink-ser7-co.nix
    ./base/developer.nix
  ];

  boot.kernelParams = [
    "amd_pstate=active" # 주전원 전력공급 시 충분한 성능을 제공하는 세팅
    # "amd_pstate=passive" # USB-PD 전력공급 시 컴퓨터가 픽하고 꺼지는걸 방지하는 세팅
  ];

  fileSystems."/boot" =
    { device = "/dev/disk/by-uuid/C125-54BB";
      fsType = "vfat";
      options = [ "fmask=0022" "dmask=0022" ];
    };

  services = {
    # 주전원 전력공급 시 충분한 성능을 제공하는 세팅
    auto-cpufreq = {
      enable = true;

      settings.charger = {
        governor = "performance";
        turbo = "always";
      };
    };

    # USB-PD 전력공급 시 컴퓨터가 픽하고 꺼지는걸 방지하는 세팅
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

  # MTU를 낮춰 Vivaldi 동기화 서버와의 문제 등을 회피함 (Tailscale, Double-NAT 등의 환경이 잦으므로 설정)
  networking.interfaces = {
    enp1s0.mtu = 1400; # 유선
    wlp2s0.mtu = 1400; # 무선
  };
}
