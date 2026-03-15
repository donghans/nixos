{ pkgs, lib, metaConfig, ... }: {
  imports = [ ../../lib/hyprland.home.nix ];

  home.username = metaConfig.username;
  home.homeDirectory = "/home/${metaConfig.username}";

  home.packages = with pkgs; [
    jetbrains.idea
    jetbrains.webstorm
    android-studio
    zed-editor

    nodejs_20
    python311
    nodePackages.yarn
    flutter
  ];

  programs.git.enable = true;
  programs.git.settings.user.name  = metaConfig.gitName;
  programs.git.settings.user.email = metaConfig.gitEmail;
}
