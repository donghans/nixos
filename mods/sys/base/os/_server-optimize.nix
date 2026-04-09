{
  config,
  pkgs,
  lib,
  ...
}:
lib.mkIf config.mods.sys.server.enable {
  boot = {
    # (이유: intel_iommu/iommu=pt는 x86 전용 — ARM은 arm-smmu로 별도 처리)
    kernelParams = lib.optionals pkgs.stdenv.hostPlatform.isx86_64 [
      "intel_iommu=on" # 가상화 하드웨어 가속
      "iommu=pt"
    ];
  };

  # (목적: 서버용 고성능 네트워크 및 파일 시스템 최적화)
  boot.kernel.sysctl = {
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
}
