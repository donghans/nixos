{...}: {
  imports = [./_hardware.nix];

  # == Boot ==
  # (목적: iso.setup.sh가 mkfs.fat -n boot 으로 레이블을 지정하므로 label 참조)
  # (참고: EFI/systemd-boot는 _boot.nix에서 isRpi 감지 시 자동 비활성화됨)
  fileSystems."/boot" = {
    device = "/dev/disk/by-label/boot";
    fsType = "vfat";
    options = ["fmask=0022" "dmask=0022"];
  };
}
