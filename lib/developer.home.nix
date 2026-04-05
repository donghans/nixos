{
  pkgs,
  unstable,
  unstable-fallback,
  ...
}: {
  imports = [
    ./_base/hyprland.home.nix
    ./developer.home/devbox.nix
    ./developer.home/fvm.nix
    ./developer.home/jetbrains.nix
    ./developer.home/node.nix
    ./developer.home/python.nix
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

  xdg.mimeApps.defaultApplications = {
    "x-scheme-handler/slack" = ["slack.desktop"];
  };
}
