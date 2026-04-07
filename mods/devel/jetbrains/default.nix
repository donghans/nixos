{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
} @ args:
if isNixOS
then {}
else
  with lib; let
    modCfg = config.mods.devel.jetbrains;
  in {
    # == jetbrains.enable 마스터 스위치: android-studio 기본값 활성화 ==
    # (사용자는 `lib.mkForce false`로 비활성화 가능)
    config = mkMerge [
      (mkIf modCfg.enable {
        mods.devel.jetbrains.android-studio.enable = mkDefault true;
      })
      (mkIf modCfg.enable (import ./jetbrains.nix-module.nix (args // {inherit pkgs;})))
    ];
  }
