_: {
  # == Hyprland 세션 식별 변수 ==
  # (참고: 각 서비스/기능의 exec-once는 해당 파일로 분리됨)
  # - bluetooth exec-once  → mods/sys/services/bluetooth.nix
  # - networkmanager applet → mods/sys/services/networkmanager.nix
  # - tailscale systray    → mods/sys/services/tailscale.nix
  # - hyprpaper            → home/hyprpaper.nix
  # - wl-clip-persist      → home/wl-clip.nix
  # - hyprpolkitagent      → home/polkit.nix
  # - fcitx5               → home/fcitx.nix
  # - waybar               → home/waybar.nix
  home.sessionVariables = {
    XDG_CURRENT_DESKTOP = "Hyprland";
    XDG_SESSION_TYPE = "wayland";
    XDG_SESSION_DESKTOP = "Hyprland";
    ELECTRON_OZONE_PLATFORM_HINT = "auto";
  };
}
