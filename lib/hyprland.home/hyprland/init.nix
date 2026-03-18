{ pkgs, config, notifyLog, ... }: let
  cliphist = "${pkgs.cliphist}/bin/cliphist";
  wl-paste = "${pkgs.wl-clipboard}/bin/wl-paste";
in {
  imports = [ ./notify.nix ];

  wayland.windowManager.hyprland.systemd = {
    enable = true;
    variables = ["--all"];
  };

  wayland.windowManager.hyprland.settings = {
    "exec-once" = [
      # 1. 시스템 설정 관련 (uwsm 없이 직접 실행해도 무방한 것들)
      "hyprctl setcursor Bibata-Modern-Ice 24"

      # 2. 필수 서비스 (uwsm app 사용)
      "uwsm app -- fcitx5"
      "uwsm app -- ${pkgs.hyprpolkitagent}/libexec/hyprpolkitagent"
      "uwsm app -- ${pkgs.networkmanagerapplet}/bin/nm-applet"

      # 3. UI 및 배경화면 (분리 실행 권장)
      "uwsm app -- ${pkgs.waybar}/bin/waybar"
      "uwsm app -- ${pkgs.hyprpaper}/bin/hyprpaper"

      # 4. 클립보드 매니저
      "uwsm app -- ${wl-paste} --type text --watch ${cliphist} store"
      "uwsm app -- ${wl-paste} --type image --watch ${cliphist} store"

      # 5. 알림 및 로그
      "uwsm app -- notify-logger"
    ];
  };

  home.sessionVariables = {
    # 커서 설정
    XCURSOR_SIZE = "24";
    HYPRCURSOR_SIZE = "24";

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
    _JAVA_AWT_WM_NONREPARENTING = "1";
  };

  services.my-notification-logger.enable = true;
}
