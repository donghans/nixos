{ pkgs, unstable, config, ... }: {
  _module.args = {
    hyprTerm = "${pkgs.kitty}/bin/kitty";
    notifyLog = "${config.home.homeDirectory}/.local/share/notify_logs/history.log";
  };

  imports = [
    ./default.home.nix
    ./hyprland.home/fuzzel.nix
    ./hyprland.home/hyprland.nix
      ./hyprland.home/hyprland/bind.nix
      ./hyprland.home/hyprland/init.nix
      ./hyprland.home/hyprland/notify.nix
      ./hyprland.home/hyprland/ui.nix
    ./hyprland.home/hyprlock.nix
    ./hyprland.home/kitty.nix
    ./hyprland.home/mako.nix
    ./hyprland.home/waybar.nix
  ];

  home.packages = with pkgs; [
    hyprpolkitagent

    qgnomeplatform
    qgnomeplatform-qt6

    xdg-desktop-portal-gtk
    xdg-desktop-portal-hyprland
    xdg-utils

    gh

    nemo

    wl-clip-persist

    (unstable.vivaldi.override {
      proprietaryCodecs = true;
      vivaldi-ffmpeg-codecs = unstable.vivaldi-ffmpeg-codecs;
      commandLineArgs = [ "--lang=ko" ];
    })
  ];
}
