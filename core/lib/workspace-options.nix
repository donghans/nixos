{lib, ...}:
with lib; {
  options = {
    workspace = {
      username = mkOption {
        type = types.str;
        description = "Main user username";
      };
      gitName = mkOption {
        type = types.str;
        description = "Git user name";
      };
      gitEmail = mkOption {
        type = types.str;
        description = "Git user email";
      };
      nixosRepo = mkOption {
        type = types.str;
        description = "NixOS repository path or URL";
      };
      hostname = mkOption {
        type = types.str;
        description = "System hostname";
      };
      isLaptop = mkOption {
        type = types.bool;
        description = "Is this a laptop device?";
      };
      ramGb = mkOption {
        type = types.nullOr types.int;
        default = null;
        description = "RAM size in GB";
      };
      stateVersion = mkOption {
        type = types.str;
        description = "NixOS/Home-Manager state version";
      };
    };

    mods = {
      sys = {
        base.enable = mkEnableOption "System Base (Zsh, Atuin, Git, CLI Tools)";
        utils.nfd.enable = mkEnableOption "NFD macOS filename fix tools";
        vfs.enable = mkEnableOption "Virtual File Systems (GVFS, Udisks2, trash-cli)";
        fonts.enable = mkEnableOption "CJK and Nerd Fonts";
        services = {
          bluetooth.enable = mkEnableOption "Bluetooth support";
          networkmanager.enable = mkEnableOption "NetworkManager (nmcli + nm-applet)";
          tailscale.enable = mkEnableOption "Tailscale Mesh VPN";
          docker.enable = mkEnableOption "Docker Daemon and tools";
        };
      };
      gui = {
        enable = mkEnableOption "GUI Bundle (Hyprland, Waybar, etc)";
        apps = {
          vivaldi.enable = mkEnableOption "Vivaldi Browser";
          slack.enable = mkEnableOption "Slack";
          bitwarden.enable = mkEnableOption "Bitwarden";
        };
        utils.notifications_logger.enable = mkEnableOption "Custom Notification Logger";
      };
      devel = {
        enable = mkEnableOption "Master switch for developer workshop";
        node.enable = mkEnableOption "Node.js toolchain";
        python.enable = mkEnableOption "Python toolchain";
        fvm.enable = mkEnableOption "Flutter Version Management";
        devbox.enable = mkEnableOption "Devbox global profile";
        llm-cli.enable = mkEnableOption "LLM CLI tools";
        zed.enable = mkEnableOption "Zed editor";
        jetbrains = {
          enable = mkEnableOption "Jetbrains common configs";
          android-studio.enable = mkEnableOption "Android Studio (ADB, UDP 5353)";
        };
      };

      # == Presets: 완성된 구성 레시피 ==
      _preset = {
        workstation.enable = mkEnableOption "워크스테이션 프리셋 (sys+services+gui+devel 일괄 활성화)";
      };
    };
  };
}
