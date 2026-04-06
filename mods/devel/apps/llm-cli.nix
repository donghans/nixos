{
  config,
  lib,
  unstable,
  unstable-fallback,
  isNixOS ? false,
  ...
}:
if isNixOS
then {}
else
  with lib; let
    cfg = config.mods.devel;
    modCfg = config.mods.devel.llm-cli;
  in {
    config = mkIf (cfg.enable || modCfg.enable) {
      home.packages = [unstable-fallback.claude-code unstable.gemini-cli];
    };
  }
