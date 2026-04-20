{
  mkMod,
  lib,
  ...
}: let
  inherit (import ../_lib.nix {inherit lib;}) importDir;
  # default.nix는 __curPos가 "mods.devel.default" 경로를 생성하므로 mkMod로 명시적 경로 사용
  base = mkMod "mods.devel" "Master switch for developer workshop" ({
    cfg,
    lib,
    ...
  }: let
    cascade = {
      mods.devel.toolchains.node.enable = lib.mkDefault true;
      mods.devel.toolchains.python.enable = lib.mkDefault true;
      mods.devel.toolchains.fvm.enable = lib.mkDefault true;
      mods.devel.toolchains.devbox.enable = lib.mkDefault true;
      mods.devel.apps.llm-cli.enable = lib.mkDefault true;
      mods.devel.apps.zed.enable = lib.mkDefault true;
      mods.devel.toolchains.jetbrains.enable = lib.mkDefault true;
    };
  in {
    # == devel.enable 마스터 스위치: 하위 항목 기본값 활성화 ==
    # (사용자는 개별 항목을 `lib.mkForce false`로 비활성화 가능)
    os = cascade;
    hm = cascade;
  });
in {
  imports = base.imports ++ importDir ./toolchains ++ importDir ./apps;
}
