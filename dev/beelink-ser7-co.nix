{ config, ... }: {
  imports = [ ./base/developer.nix ];

  boot.kernelParams = [ "amd_pstate=active" ];

  fileSystems."/boot" =
    { device = "/dev/disk/by-uuid/C125-54BB";
      fsType = "vfat";
      options = [ "fmask=0022" "dmask=0022" ];
    };

  services = {
    auto-cpufreq = {
      enable = true;

      settings.charger = {
        governor = "performance";
        turbo = "always";
      };
    };

    irqbalance.enable = true;
  };

  # MTU를 낮춰 Vivaldi 동기화 서버와의 문제 등을 회피함 (Tailscale, Double-NAT 등의 환경이 잦으므로 설정)
  networking.interfaces = {
    enp1s0.mtu = 1400; # 유선
    wlp2s0.mtu = 1400; # 무선
  };
}
