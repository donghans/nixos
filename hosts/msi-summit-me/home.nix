{lib, ...}: {
  # == Home Configuration ==

  wayland.windowManager.hyprland = {
    touchpadToggleKey = "$mainMod CTRL, XF86TouchpadToggle";
    lidSwitchOnExtraCmd = "tlp bat";
    lidSwitchOffExtraCmd = "tlp start";
    settings = {
      monitor = lib.mkForce [
        "eDP-1,2560x1600@60,auto,1"
        "DP-2,preferred,auto-up,1"
      ];

      input.touchpad = {
        natural_scroll = true;
        tap-to-click = true;
        disable_while_typing = true;
      };
    };
  };

  # == 프리셋: 워크스테이션 전체 도메인 활성화 ==
  mods._preset.workstation.enable = true;

  # == 호스트별 앱 선택 ==
  mods.gui.apps.vivaldi.enable = true;
  mods.gui.apps.slack.enable = true;
  mods.gui.apps.bitwarden.enable = true;
  mods.gui.utils.notifications_logger.enable = true;
  mods.devel.jetbrains.android-studio.enable = true;
}
