{
  config,
  lib,
  unstable,
  unstable-fallback,
  ...
}:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.llm-cli;
in {
  config = mkIf (cfg.enable || modCfg.enable) {
    home.packages = [unstable-fallback.claude-code unstable.gemini-cli];
  };
}
