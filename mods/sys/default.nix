{isNixOS ? false, ...}: {
  imports =
    [
      ./fonts.nix
      ./vfs.nix
      ./utils/nfd.nix
      ./services/bluetooth.nix
      ./services/docker.nix
      ./services/networkmanager.nix
      ./services/tailscale.nix
    ]
    ++ [
      (
        if isNixOS
        then ./base/os.nix
        else ./base/home.nix
      )
    ];
}
