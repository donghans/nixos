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
    ./hyprland.home/bind.hwctl.nix
    ./hyprland.home/notify.nix
    ./hyprland.home/ui.nix
    ./hyprland.home/winrule.nix
    ./hyprland.home/ext/fuzzel.nix
    ./hyprland.home/ext/hyprlock.nix
    ./hyprland.home/ext/kitty.nix
    ./hyprland.home/ext/mako.nix
    ./hyprland.home/ext/waybar.nix
    ./vivaldi.home/_init.nix
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
  ];
  # == Hide Clutter in Application Menu ==
  # (목적: 사용 빈도가 낮거나 배경에서 실행되는 도구들의 실행 아이콘을 숨겨 메뉴를 정리)
  xdg.desktopEntries = {
    "blueman-adapters" = {
      name = "Bluetooth Adapters (Hidden)";
      noDisplay = true;
    };
    "org.fcitx.Fcitx5" = {
      name = "Fcitx 5 (Hidden)";
      noDisplay = true;
    };
    "org.fcitx.fcitx5-migrator" = {
      name = "Fcitx 5 Migration Wizard (Hidden)";
      noDisplay = true;
    };
    "kbd-layout-viewer5" = {
      name = "Keyboard Layout Viewer (Hidden)";
      noDisplay = true;
    };
    "nixos-manual" = {
      name = "NixOS Manual (Hidden)";
      noDisplay = true;
    };
    "uuctl" = {
      name = "UWSM Control (Hidden)";
      noDisplay = true;
    };
  };
}
