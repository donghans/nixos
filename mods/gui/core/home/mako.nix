# [working-refactor] 해당 구문은 before-refactor/lib/_base/hyprland.home/mako.nix 에 있었음
# [working-refactor] 해당 구문은 after-refactor/... 로 들어가야 함
_: {
  services.mako.enable = true;

  services.mako.settings = {
    default-timeout = 5000; # ms
    background-color = "#282a36";
  };
}
