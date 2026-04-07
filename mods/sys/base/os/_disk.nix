{pkgs, ...}: {
  # == Btrfs 파일시스템 ==
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
      "compress=zstd:3"
      "noatime"
      "discard=async"
      "space_cache=v2"
    ];
  };

  fileSystems."/nix" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "btrfs";
    options = [
      "subvol=@nix"
      "compress=zstd:3"
      "noatime"
      "discard=async"
      "space_cache=v2"
    ];
  };

  fileSystems."/var/log" = {
    device = "/dev/disk/by-label/nixos";
    fsType = "btrfs";
    options = [
      "subvol=@log"
      "compress=zstd:3"
      "noatime"
      "discard=async"
      "space_cache=v2"
    ];
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
}
