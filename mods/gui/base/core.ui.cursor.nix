{mkPartOf, ...}:
# (목적: GUI 비활성 환경에서 gtk/pointerCursor 설정이 dconf에 접근하는 것을 차단)
mkPartOf "mods.gui" ({
  pkgs,
  lib,
  ...
}: let
  cursorEnv = {
    XCURSOR_SIZE = "24";
    HYPRCURSOR_SIZE = "24";
    XCURSOR_THEME = "Bibata-Modern-Ice";
  };
in {
  hm = {
    # == 커서 테마 ==
    # Hyprland 커서 초기화
    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 900 [
      "hyprctl setcursor Bibata-Modern-Ice 24"
    ];

    # Home Manager 포인터 커서 (GTK 앱 포함)
    home.pointerCursor = {
      gtk.enable = true;
      package = pkgs.bibata-cursors;
      name = "Bibata-Modern-Ice";
      size = 24;
    };

    # GTK 커서 테마
    gtk.cursorTheme = {
      name = "Bibata-Modern-Ice";
      package = pkgs.bibata-cursors;
    };

    # 환경 변수 (XWayland 및 기타 앱)
    # home.sessionVariables 는 hm-session-vars.sh 를 읽는 zsh 셸에만 닿는다. uwsm 로그인에는 ~/.profile·uwsm/env 가 없어
    # Hyprland·systemd 사용자 환경에는 이 변수가 없었고, XWayland 앱(ONLYOFFICE 등)의 커서가 2배로 보였다. 앱이 뜨는 경로가 둘이라 각각에 넣는다.
    #  - thunar.service 처럼 systemd 서비스로 뜨는 앱: systemd 사용자 관리자 환경 (environment.d)
    #  - `uwsm app` scope(Super+Space 런처 등): 호출한 Hyprland 의 환경 → hl.env (예전 hyprland.conf 의 `env =` 가 Lua 이전 때 빠졌었음)
    home.sessionVariables = cursorEnv;
    systemd.user.sessionVariables = cursorEnv;
    wayland.windowManager.hyprland.extraConfig = ''
      hl.env("XCURSOR_SIZE", "24")
      hl.env("HYPRCURSOR_SIZE", "24")
      hl.env("XCURSOR_THEME", "Bibata-Modern-Ice")
    '';
  };
})
