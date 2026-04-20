_: {
  # == Boot & Kernel ==
  boot = {
    kernelParams = [
      "amd_pstate=active" # (이유: 주전원 공급 시 성능 최적화)
      # [OPTIONAL] "amd_pstate=passive" (이유: USB-PD 전력 부족 시 강제 종료 방지)
    ];
  };

  # == Services & Networking ==
  # (참고: TLP 전원 관리는 mods/sys/base/os/_power.nix에서 desktop 프로파일로 자동 적용됨)
  # (참고: USB-PD 전력 부족 시 turbo 제어가 필요하면 services.tlp.settings.CPU_BOOST_ON_AC = 0 추가)
  services.irqbalance.enable = true;
}
