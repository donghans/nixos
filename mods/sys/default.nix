{
  lib,
  isNixOS ? false,
  ...
}:
with lib; {
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

  options.mods.sys.base.enable = mkEnableOption "System Base (Zsh, Atuin, Git, CLI Tools)";
}
