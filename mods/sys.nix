{lib, ...}: {
  options.mods.sys.base.enable = lib.mkEnableOption "System Base (Zsh, Atuin, Git, CLI Tools)";
  options.mods.sys.server.enable = lib.mkEnableOption "Server-optimized Kernel/Network settings";
}
