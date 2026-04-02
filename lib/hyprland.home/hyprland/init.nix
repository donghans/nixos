{ pkgs, config, notifyLog, ... }: let
  cliphist = "${pkgs.cliphist}/bin/cliphist";
  wl-paste = "${pkgs.wl-clipboard}/bin/wl-paste";
in {
  wayland.windowManager.hyprland.systemd = {
    enable = true;
    variables = ["--all"];
  };

  wayland.windowManager.hyprland.settings = {
    exec-once = [
      # 시스템 설정 관련 (uwsm 없이 직접 실행해도 무방한 것들)
      "rfkill unblock bluetooth && bluetoothctl power on"

      # 필수 서비스 (uwsm app 사용)
      "uwsm app -- fcitx5"
      "uwsm app -- ${pkgs.hyprpolkitagent}/libexec/hyprpolkitagent"
      "uwsm app -- ${pkgs.networkmanagerapplet}/bin/nm-applet"

      # UI 및 배경화면 (분리 실행 권장)
      "uwsm app -- ${pkgs.waybar}/bin/waybar"
      "uwsm app -- ${pkgs.hyprpaper}/bin/hyprpaper"

      # 클립보드 안정성 및 지속성 (XWayland 브릿지 역할)
      "uwsm app -- ${pkgs.wl-clip-persist}/bin/wl-clip-persist --clipboard regular"

      # 사용자 앱
      "uwsm app -- ${pkgs.tailscale}/bin/tailscale systray"
    ];
  };

  home.sessionVariables = {
    # 커서 설정
    XCURSOR_SIZE = "24";
    HYPRCURSOR_SIZE = "24";
    XCURSOR_THEME = "Bibata-Modern-Ice";

    # 입력기 (Fcitx5)
    GTK_IM_MODULE = ""; # GTK4부터는 비워두는 것이 권장됩니다.
    QT_IM_MODULE = "fcitx";
    XMODIFIERS = "@im=fcitx";
    SDL_IM_MODULE = "fcitx";
    INPUT_METHOD = "fcitx";

    # 테마 및 플랫폼
    GTK_THEME = "Adwaita-dark";
    QT_QPA_PLATFORM = "wayland;xcb"; # xcb fallback 추가 권장

    # 데스크탑 환경 식별
    XDG_CURRENT_DESKTOP = "Hyprland";
    XDG_SESSION_TYPE = "wayland";
    XDG_SESSION_DESKTOP = "Hyprland";

    # 기타 앱 힌트
    ELECTRON_OZONE_PLATFORM_HINT = "auto";
  };

  xdg = {
    portal.enable = true;
    portal.extraPortals = with pkgs; [
      xdg-desktop-portal-hyprland # 화면 공유용
      xdg-desktop-portal-gtk      # 파일 선택/테마용
    ];

    portal.config.common.default = [ "hyprland" "gtk" ];

    mimeApps.enable = true;
  };

  programs = {
    bash.enable = true;

    git.settings.credential.helper = "${pkgs.gh}/bin/gh auth git-credential";
  };

  services.cliphist.enable = true;

  services.my-notification-logger.enable = true;
}
