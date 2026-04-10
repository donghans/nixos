{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  modCfg = config.mods.devel.node;
in
  {
    options.mods.devel.node.enable = mkEnableOption "Node.js toolchain";
  }
  // (
    if isNixOS
    then {}
    else {
      config = mkIf modCfg.enable {
        home.packages = with pkgs; [
          node-wrapped
          pnpm-wrapped
          pnpm-yarn-wrapper
        ];

        home.sessionVariables = {
          PNPM_PACKAGE_IMPORT_METHOD = "reflink"; # (이유: Btrfs CoW 활용 성능 최적화)
          PNPM_PUBLIC_HOIST_PATTERN = "*";
          PNPM_SHAMEFULLY_HOIST = "true"; # (이유: 패키지 호이스팅 호환성 극대화)
          PNPM_STORE_DIR = "/home/${config.workspace.username}/.local/share/pnpm/store";
        };

        home.shellAliases = {
          npm = "pnpm";
          npx = "pnpm dlx";
        };
      };
    }
  )
