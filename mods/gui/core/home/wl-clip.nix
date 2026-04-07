{
  pkgs,
  lib,
  config,
  ...
}:
with lib; {
  # == 클립보드 관리 ==
  config = mkIf config.mods.gui.enable {
    # 클립보드 내용을 앱 종료 후에도 유지
    wayland.windowManager.hyprland.settings.exec-once = [
      "uwsm app -- ${pkgs.wl-clip-persist}/bin/wl-clip-persist --clipboard regular"
    ];
    home.packages = [pkgs.wl-clip-persist];

    # 클립보드 히스토리 매니저
    services.cliphist.enable = true;
  };
}
