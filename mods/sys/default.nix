{
  lib,
  isNixOS ? false,
  ...
}: let
  inherit (import ../_lib.nix {inherit lib;}) importDir;
in {
  imports =
    [
      ./fonts.nix
      ./vfs.nix
      # sys/base/os.nix와 sys/base/home.nix의 sub-imports가 컨텍스트 전용이므로 분기 유지
      (
        if isNixOS
        then ./base/os.nix
        else ./base/home.nix
      )
    ]
    ++ importDir ./utils
    ++ importDir ./services;

  options.mods.sys.base.enable = lib.mkEnableOption "System Base (Zsh, Atuin, Git, CLI Tools)";
  options.mods.sys.server.enable = lib.mkEnableOption "Server-optimized Kernel/Network settings";
}
