# ISO 의 `nixseal` 래퍼(luks·status·recover 용 도구 모음). ISO(core/iso.nixstrap.nix)와 VM 시험(core/scripts/tests/vm/sb-recover.nix)이 같은 것을 쓴다 —
# 시험이 ISO 에 실제로 들어가는 PATH 를 그대로 검증하게 하려고 분리했다.
# recover(plan/nixseal-recover)가 부르는 도구: mount·umount·mountpoint·findmnt·lsblk·blkid(util-linux)·dd(coreutils)·tar·mkfs.vfat(dosfstools)·
# efibootmgr·nixos-enter(nixos-install-tools)·sbctl(대상의 sbctl 은 chroot 안에서 쓰고, 여기 것은 status 출력용)·cryptsetup·btrfs-progs(서브볼륨 마운트).
{
  pkgs,
  script, # nixseal.py 의 경로(store 안)
}:
pkgs.writeShellApplication {
  name = "nixseal";
  runtimeInputs = [pkgs.python3 pkgs.cryptsetup pkgs.util-linux pkgs.coreutils pkgs.qrencode pkgs.gnutar pkgs.dosfstools pkgs.efibootmgr pkgs.btrfs-progs pkgs.nixos-install-tools pkgs.sbctl];
  text = ''
    exec python3 -I ${script} "$@"
  '';
}
