{
  lib,
  config,
  ...
}: {
  # == 물리적 스왑 파일 ==
  # (목적: 물리 RAM 기반 스왑 — ramGb 메타데이터가 있을 때만 동적으로 생성)
  swapDevices = lib.optionals (config.workspace ? ramGb && config.workspace.ramGb != null) [
    {
      device = "/var/lib/swapfile";
      size = config.workspace.ramGb * 1024;
      priority = 10;
    }
  ];

  # == ZRAM 스왑 ==
  # (목적: 메모리 압축 스왑 — 기본적으로 활성화하되 리소스 사용 최적화)
  zramSwap = {
    enable = true;
    algorithm = "zstd";
    memoryPercent = 50;
    priority = 100;
  };

  # == tmpfs (/tmp) ==
  # (목적: /tmp 공간을 RAM(tmpfs)으로 사용 — ramGb가 명시된 호스트만 150% 할당)
  boot.tmp = {
    useTmpfs = lib.mkDefault true;
    tmpfsSize =
      if (config.workspace ? ramGb && config.workspace.ramGb != null)
      then "150%"
      else "50%";
  };
}
