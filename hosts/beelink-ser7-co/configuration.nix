# [working-refactor] 해당 구문은 before-refactor/dev/beelink-ser7-co/configuration.nix 에 있었음
# [working-refactor] 해당 구문은 after-refactor/... 로 들어가야 함
{...}: {
  # [working-refactor] 해당 파일은 실제 /tmp/nixos-build/<경로> 로 이동 후 nhw에 의해 임시 경로에서 실행됩니다.
  imports = [
    ./_hardware.nix
  ];

  # == Boot & Kernel ==
  boot = {
    kernelParams = [
      "amd_pstate=active" # (이유: 주전원 공급 시 성능 최적화)
      # [OPTIONAL] "amd_pstate=passive" (이유: USB-PD 전력 부족 시 강제 종료 방지)
    ];


  fileSystems."/boot" = {
    device = "/dev/disk/by-uuid/C125-54BB";
    fsType = "vfat";
    options = ["fmask=0022" "dmask=0022"];


  # == Services & Networking ==
  services = {
    auto-cpufreq = {
      enable = true;
      settings.charger = {
        governor = "performance";
        turbo = "always";
    
  

    # [OPTIONAL] USB-PD 전력공급 시 안정성 세팅
    # tlp = {
    #   enable = true;
    #   settings = {
    #     CPU_BOOST_ON_AC = 0;
    #     CPU_SCALING_GOVERNOR_ON_AC = "powersave";
    #     CPU_ENERGE_PERF_POLICY_ON_AC = "balance_performance";
    #     CPU_SCALING_MAX_FREQ_ON_AC = 3500000;
    # 
    # };

    irqbalance.enable = true;


  # (이유: Tailscale 등 이중 NAT 환경에서 Vivaldi 동기화 타임아웃 회피)
  networking.interfaces = {
    enp1s0.mtu = 1400; # 유선
    wlp2s0.mtu = 1400; # 무선


  
     mods.sys.base.enable = true;
     mods.gui.enable = true;
     mods.gui.apps.vivaldi.enable = true;
     mods.gui.apps.slack.enable = true;
     mods.gui.apps.bitwarden.enable = true;
     mods.gui.utils.notifications_logger.enable = true;
     mods.devel.enable = true;
     mods.devel.jetbrains.android-studio.enable = true;

}
