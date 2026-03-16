{ pkgs, lib, metaConfig, ... }: {
  imports = [ ../../lib/hyprland.home.nix ];

  home.username = metaConfig.username;
  home.homeDirectory = "/home/${metaConfig.username}";

  home.packages = with pkgs; [
    bitwarden-desktop
    bitwarden-cli

    slack

    jetbrains.idea
    jetbrains.webstorm
    android-studio
    zed-editor

    antigravity
    jdk21

    nodejs_20
    python311
    nodePackages.yarn
    flutter
  ];

  programs.git.enable = true;
  programs.git.settings.user.name  = metaConfig.gitName;
  programs.git.settings.user.email = metaConfig.gitEmail;
}
