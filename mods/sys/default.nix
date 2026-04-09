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
      ./services/incus.nix
      ./services/headscale.nix
      ./services/caddy.nix
      ./services/cockpit.nix
      ./services/frp.nix
    ]
    ++ [
      (
        if isNixOS
        then ./base/os.nix
        else ./base/home.nix
      )
    ];

  options.mods.sys.base.enable = mkEnableOption "System Base (Zsh, Atuin, Git, CLI Tools)";
  options.mods.sys.serverMode.enable = mkEnableOption "Server-optimized Kernel/Network settings";
}
