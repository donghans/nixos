# [working-refactor] 해당 구문은 before-refactor/dev/base.dev.nix 에 있었음
# [working-refactor] 해당 구문은 after-refactor/... 로 들어가야 함
{
  lib,
  pkgs,
  metaConfig,
  ...
}: {
  # == Boot & Kernel ==
  # (목적: rEFInd 호환성을 위한 시스템디 부트 최소 설정)
  boot = {
    loader.systemd-boot.enable = true;
    loader.efi.canTouchEfiVariables = true;
    loader.efi.efiSysMountPoint = "/boot";
    kernelPackages = pkgs.linuxPackages;
  };

  fileSystems."/" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "btrfs";
    options = [
      "subvol=@"
      "compress=zstd:3" # 압축 수준 3 (성능과 압축률의 최적 지점)
      "noatime" # 파일 읽을 때마다 시간을 기록하지 않음 (SSD 성능 향상)
      "discard=async" # 백그라운드에서 TRIM 실행 (Linux 5.6+ 권장)
      "space_cache=v2" # 최신 공간 캐시 알고리즘
    ];
  };

  fileSystems."/home" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "btrfs";
    options = [
      "subvol=@home"
      "compress=zstd:3" # 압축 수준 3 (성능과 압축률의 최적 지점)
      "noatime" # 파일 읽을 때마다 시간을 기록하지 않음 (SSD 성능 향상)
      "discard=async" # 백그라운드에서 TRIM 실행 (Linux 5.6+ 권장)
      "space_cache=v2" # 최신 공간 캐시 알고리즘
    ];
  };

  fileSystems."/nix" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "btrfs";
    options = [
      "subvol=@nix"
      "compress=zstd:3" # 압축 수준 3 (성능과 압축률의 최적 지점)
      "noatime" # 파일 읽을 때마다 시간을 기록하지 않음 (SSD 성능 향상)
      "discard=async" # 백그라운드에서 TRIM 실행 (Linux 5.6+ 권장)
      "space_cache=v2" # 최신 공간 캐시 알고리즘
    ];
  };

  fileSystems."/var/log" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "btrfs";
    options = [
      "subvol=@log"
      "compress=zstd:3" # 압축 수준 3 (성능과 압축률의 최적 지점)
      "noatime" # 파일 읽을 때마다 시간을 기록하지 않음 (SSD 성능 향상)
      "discard=async" # 백그라운드에서 TRIM 실행 (Linux 5.6+ 권장)
      "space_cache=v2" # 최신 공간 캐시 알고리즘
    ];
  };

  # 물리적 스왑 파일 설정 (ramGb 메타데이터가 있을 때만 동적으로 생성)
  swapDevices = lib.optionals (metaConfig ? ramGb && metaConfig.ramGb != null) [
    {
      device = "/var/lib/swapfile";
      size = metaConfig.ramGb * 1024;
      priority = 10;
    }
  ];

  # 주기적인 Scrub (데이터 무결성 검사 및 복구)
  services = {
    btrfs.autoScrub = {
      enable = true;
      interval = "weekly";
      fileSystems = ["/"];
    };

    fstrim.enable = true;
  };

  # 메모리 최적화 (zram) - 기본적으로 활성화하되 리소스 사용 최적화
  zramSwap = {
    enable = true;
    algorithm = "zstd";
    memoryPercent = 50;
    priority = 100;
  };

  # /tmp 공간을 RAM(tmpfs)으로 사용 (ramGb가 명시된 호스트만 150% 할당)
  boot.tmp = {
    useTmpfs = lib.mkDefault true;
    tmpfsSize =
      if (metaConfig ? ramGb && metaConfig.ramGb != null)
      then "150%"
      else "50%";
  };

  # Snapper 설정 (시스템 서비스) TODO 적절한 백업 주기 및 서브볼륨 분리할 것
  # services.snapper = {
  #   snapshotInterval = "hourly"; # 기본 주기
  #   configs = {
  #     home = {
  #       SUBVOLUME = "/home";
  #       TIMELINE_CREATE = true;
  #       TIMELINE_CLEANUP = true;
  #     };
  #     # 앞서 논의한 Downloads 전용 설정 등 추가 가능
  #   };
  # };

  # (선택사항) btrbk 설정
  # services.btrbk.instances."local" = { ... };

  hardware.bluetooth = {
    enable = true;
    powerOnBoot = true;
  };

  services.blueman.enable = true;

  hardware.graphics.enable = true;
  hardware.graphics.enable32Bit = true;

  environment.systemPackages = with pkgs; [
    btrfs-progs
    # snapper
    # btrbk
  ];
}
