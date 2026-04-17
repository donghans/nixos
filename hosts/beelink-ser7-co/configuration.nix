{...}: {
  imports = [
    ./_hardware.nix
  ];

  # == Boot & Kernel ==
  boot = {
    kernelParams = [
      "amd_pstate=active" # (이유: 주전원 공급 시 성능 최적화)
      # [OPTIONAL] "amd_pstate=passive" (이유: USB-PD 전력 부족 시 강제 종료 방지)
    ];
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
    #     CPU_ENERGY_PERF_POLICY_ON_AC = "balance_performance";
    #     CPU_SCALING_MAX_FREQ_ON_AC = 3500000;
    #   };
    # };

    irqbalance.enable = true;
  };

}
