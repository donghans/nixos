{mkPartOf, ...}:
# (목적: GUI 비활성 환경에서 gtk/pointerCursor 설정이 dconf에 접근하는 것을 차단)
mkPartOf "mods.gui" ({
  pkgs,
  lib,
  ...
}: {
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
    home.sessionVariables = {
      XCURSOR_SIZE = "24";
      HYPRCURSOR_SIZE = "24";
      XCURSOR_THEME = "Bibata-Modern-Ice";
    };
  };
})
