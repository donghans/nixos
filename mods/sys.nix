{
  lib,
  isNixOS ? false,
  ...
}: let
  inherit (import ./_lib.nix {inherit lib;}) importDir;
in {
  imports =
    [
      ./sys/fonts.nix
      ./sys/vfs.nix
      # sys/base/os.nix와 sys/base/home.nix의 sub-imports가 컨텍스트 전용이므로 분기 유지
      # (Phase 3에서 mkPartOf 전환 완료 후 조건 제거 예정)
      (
        if isNixOS
        then ./sys/base/os.nix
        else ./sys/base/home.nix
      )
    ]
    ++ importDir ./sys/utils
    ++ importDir ./sys/services;

  options.mods.sys.base.enable = lib.mkEnableOption "System Base (Zsh, Atuin, Git, CLI Tools)";
  options.mods.sys.server.enable = lib.mkEnableOption "Server-optimized Kernel/Network settings";
}
