{isNixOS ? false, ...}: {
  imports =
    [
      ../fonts.nix
      ../vfs.nix
      ../utils/nfd.nix
      ../services/bluetooth.nix
      ../services/docker.nix
      ../services/tailscale.nix
    ]
    ++ (
      if isNixOS
      then [
        ./os.nix
        ../../../hosts/base.dev.nix # (목적: Btrfs/ZRAM/스토리지 설정 — sys 도메인 소속)
      ]
      else []
    )
    ++ (
      if !isNixOS
      then [./home.nix]
      else []
    );
}
