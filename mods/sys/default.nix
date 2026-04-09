{
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  inherit (import ../_lib.nix {inherit lib;}) importDir;
in {
  imports =
    [
      ./fonts.nix
      ./vfs.nix
    ]
    ++ importDir ./utils
    ++ importDir ./services
    ++ [
      (
        if isNixOS
        then ./base/os.nix
        else ./base/home.nix
      )
    ];

  options.mods.sys.base.enable = mkEnableOption "System Base (Zsh, Atuin, Git, CLI Tools)";
  options.mods.sys.server.enable = mkEnableOption "Server-optimized Kernel/Network settings";
}
