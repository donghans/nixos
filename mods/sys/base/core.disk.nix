{mkPartOf, ...}:
mkPartOf "mods.sys.base" ({
  pkgs,
  config,
  ...
}: let
  # 공통 Btrfs 마운트 옵션 (subvol만 마운트 포인트별로 다름)
  btrfsOpts = subvol: [
    "subvol=${subvol}"
    "compress=zstd:3" # 압축 수준 3 (성능과 압축률의 최적 지점)
    "noatime" # 파일 읽을 때마다 시간을 기록하지 않음 (SSD 성능 향상)
    "discard=async" # 백그라운드에서 TRIM 실행 (Linux 5.6+ 권장)
    "space_cache=v2" # 최신 공간 캐시 알고리즘
  ];
in {
  os = {
    # == Boot 파티션 ==
    fileSystems."/boot" = {
      device = config.workspace.bootDevice;
      fsType = "vfat";
      options = ["fmask=0137" "dmask=0027"];
    };

    # == Btrfs 파일시스템 ==
    fileSystems."/" = {
      device = config.workspace.diskDevice;
      fsType = "btrfs";
      options = btrfsOpts "@";
    };

    fileSystems."/home" = {
      device = config.workspace.diskDevice;
      fsType = "btrfs";
      options = btrfsOpts "@home";
    };

    fileSystems."/nix" = {
      device = config.workspace.diskDevice;
      fsType = "btrfs";
      options = btrfsOpts "@nix";
    };

    fileSystems."/var/log" = {
      device = config.workspace.diskDevice;
      fsType = "btrfs";
      options = btrfsOpts "@log";
    };

    # == Btrfs 유지보수 서비스 ==
    services = {
      # 주기적인 Scrub (데이터 무결성 검사 및 복구)
      btrfs.autoScrub = {
        enable = true;
        interval = "weekly";
        fileSystems = ["/"];
      };

      fstrim.enable = true;
    };

    environment.systemPackages = with pkgs; [
      btrfs-progs
      # snapper
      # btrbk
    ];
  };
})
