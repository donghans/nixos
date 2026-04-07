{
  config,
  lib,
  unstable,
  unstable-fallback,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.devel;
  modCfg = config.mods.devel.llm-cli;
in
  {options.mods.devel.llm-cli.enable = mkEnableOption "LLM CLI tools";}
  // (
    if isNixOS
    then {}
    else {
      config = mkIf (cfg.enable || modCfg.enable) {
        home.packages = [unstable-fallback.claude-code unstable.gemini-cli];
      };
    }
  )
