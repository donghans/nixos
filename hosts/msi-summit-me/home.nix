# [working-refactor] 해당 구문은 before-refactor/dev/msi-summit-me/home.nix 에 있었음
# [working-refactor] 해당 구문은 after-refactor/... 로 들어가야 함
{lib, ...}: {
  # == Home Configuration ==
  # [working-refactor] 해당 파일은 실제 /tmp/nixos-build/<경로> 로 이동 후 nhw에 의해 임시 경로에서 실행됩니다.

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
    
  


  
     mods.sys.base.enable = true;
     mods.gui.enable = true;
     mods.gui.apps.vivaldi.enable = true;
     mods.gui.apps.slack.enable = true;
     mods.gui.apps.bitwarden.enable = true;
     mods.gui.utils.notifications_logger.enable = true;
     mods.devel.enable = true;
     mods.devel.jetbrains.android-studio.enable = true;

}
