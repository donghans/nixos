{
  mkMod,
  lib,
  ...
}: let
  inherit (import ./_lib.nix {inherit lib;}) importDir;
  # __curPos가 mods/devel.nix에서 평가되므로 경로가 "mods.devel"로 정확히 생성됨
  base = mkMod __curPos "Master switch for developer workshop" ({
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
  imports = base.imports ++ importDir ./devel/toolchains ++ importDir ./devel/apps;
}
