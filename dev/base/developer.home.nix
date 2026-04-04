{
  pkgs,
  unstable,
  unstable-fallback,
  metaConfig,
  ...
}: {
  imports = [
    ../../lib/hyprland.home.nix
    ../../lib/devbox.home/_init.nix
    ./pkgs/fvm.nix
    ./pkgs/jetbrains.nix
    ./pkgs/node.nix
    ./pkgs/python.nix
  ];

  # == Common Development Packages ==
  home.packages = with pkgs; [
    bitwarden-desktop
    bitwarden-cli

    unstable.slack
    unstable.zed-editor

    unstable-fallback.claude-code
    unstable.gemini-cli
  ];

  # == Tool Configurations ==
  programs.git = {
    enable = true;
    settings = {
      user.name = metaConfig.gitName;
      user.email = metaConfig.gitEmail;
      url."git@github.com:".insteadOf = "https://github.com/";
    };
  };

  xdg.mimeApps.defaultApplications = {
    "x-scheme-handler/slack" = ["slack.desktop"];
  };
}
