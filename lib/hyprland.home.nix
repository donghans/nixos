{
  pkgs,
  unstable,
  config,
  ...
}: {
  _module.args = {
    hyprTerm = "${pkgs.kitty}/bin/kitty";
    notifyLog = "${config.home.homeDirectory}/.local/share/notify_logs/history.log";
  };

  imports = [
    ./default.home.nix
    ./hyprland.home/_init.nix
    ./hyprland.home/bind.nix
    ./hyprland.home/notify.nix
    ./hyprland.home/ui.nix
    ./hyprland.home/winrule.nix
    ./hyprland.home/ext/fuzzel.nix
    ./hyprland.home/ext/hyprlock.nix
    ./hyprland.home/ext/kitty.nix
    ./hyprland.home/ext/mako.nix
    ./hyprland.home/ext/waybar.nix
  ];

  home.packages = with pkgs; [
    hyprpolkitagent

    qgnomeplatform
    qgnomeplatform-qt6

    xdg-desktop-portal-gtk
    xdg-desktop-portal-hyprland
    xdg-utils

    nemo

    wl-clip-persist

    (unstable.vivaldi.override {
      proprietaryCodecs = true;
      inherit (unstable) vivaldi-ffmpeg-codecs;
      commandLineArgs = ["--lang=ko"];
    })
  ];
}
