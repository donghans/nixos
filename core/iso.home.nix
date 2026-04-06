{pkgs, ...}: {
  imports = [];

  home.username = "nixos";
  home.homeDirectory = "/home/nixos";

  home.packages = with pkgs; [
    zed-editor
  ];

  # == Hide Default Application Icons ==
  # (목적: 메뉴에서 firefox와 xterm을 가려서 커스텀 인스톨러 느낌을 강화)
  xdg.desktopEntries = {
    firefox = {
      name = "Firefox (Hidden)";
      noDisplay = true;
    };
    xterm = {
      name = "XTerm (Hidden)";
      noDisplay = true;
    };
  };

  mods.sys.base.enable = true;
  mods.gui.enable = true;
  mods.gui.apps.vivaldi.enable = true;
}
