{
  pkgs,
  metaConfig,
  ...
}: {
  imports = [./lib/hyprland.home.nix];

  home.username = "nixos";
  home.homeDirectory = "/home/nixos";

  home.packages = with pkgs; [
    zed-editor
  ];

  programs.git.enable = true;
  programs.git.settings.user.name = metaConfig.gitName;
  programs.git.settings.user.email = metaConfig.gitEmail;
}
