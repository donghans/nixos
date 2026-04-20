{mkPartOf, ...}:
mkPartOf "mods.sys.base" ({
  lib,
  config,
  ...
}: let
  cfg = config.workspace;
  inherit (cfg) ramGb; # resolve.py에서 /proc/meminfo 자동 감지

  # swapGb: 명시 오버라이드 > ceil(ramGb * 0.75) > null (swap 없음)
  # ceil(n * 3/4) = (n * 3 + 3) / 4  (정수 ceil 나눗셈)
  swapGb =
    if cfg.swapGb != null
    then cfg.swapGb
    else if ramGb != null
    then (ramGb * 3 + 3) / 4
    else null;

  # tmpfsSize: 명시 오버라이드 > "100%"
  tmpfsSize =
    if cfg.tmpfsSize != null
    then cfg.tmpfsSize
    else "100%";

  # zramPercent: 명시 오버라이드 > 50
  zramPercent =
    if cfg.zramPercent != null
    then cfg.zramPercent
    else 50;
in {
  os = {
    # == 물리적 스왑 파일 ==
    # (목적: tmpfs 초과분과 프로세스 오버플로우 흡수 — ramGb 자동 감지 시 ceil(ramGb*0.75)로 생성)
    swapDevices = lib.optionals (swapGb != null && swapGb > 0) [
      {
        device = "/var/lib/swapfile";
        size = swapGb * 1024;
        priority = 10;
      }
    ];

    # == ZRAM 스왑 ==
    # (목적: 메모리 압축 스왑 — 물리 swap보다 우선(priority 100)하여 디스크 I/O 최소화)
    zramSwap = {
      enable = true;
      algorithm = "zstd";
      memoryPercent = zramPercent;
      priority = 100;
    };

    # == tmpfs (/tmp) ==
    # (목적: nixup 빌드 등 대용량 임시 파일을 RAM에서 처리 — swap이 초과분을 흡수)
    boot.tmp = {
      useTmpfs = lib.mkDefault true;
      inherit tmpfsSize;
    };
  };
})
