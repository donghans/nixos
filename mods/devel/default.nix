{
  lib,
  config,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.devel;
in {
  imports =
    [
      ./toolchains/node.nix
      ./toolchains/python.nix
      ./toolchains/fvm.nix
      ./toolchains/devbox.nix
      ./apps/llm-cli.nix
      ./apps/zed.nix
      ./jetbrains/default.nix
      ./jetbrains/android-studio.nix
    ]
    ++ [
      (
        if isNixOS
        then ./base/os.nix
        else ./base/home.nix
      )
    ];

  options.mods.devel.enable = mkEnableOption "Master switch for developer workshop";

  # == devel.enable 마스터 스위치: 하위 항목 기본값 활성화 ==
  # (사용자는 개별 항목을 `lib.mkForce false`로 비활성화 가능)
  config = mkIf cfg.enable {
    mods.devel.node.enable = mkDefault true;
    mods.devel.python.enable = mkDefault true;
    mods.devel.fvm.enable = mkDefault true;
    mods.devel.devbox.enable = mkDefault true;
    mods.devel.llm-cli.enable = mkDefault true;
    mods.devel.zed.enable = mkDefault true;
    mods.devel.jetbrains.enable = mkDefault true;
  };
}
