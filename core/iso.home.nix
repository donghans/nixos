{pkgs, ...}: {
  imports = [];

  home.username = "nixos";
  home.homeDirectory = "/home/nixos";

  home.packages = with pkgs; [
    zed-editor
  ];

  # == Hide Default Application Icons ==
  # (목적: 메뉴에서 xterm을 가려서 커스텀 인스톨러 느낌을 강화)
  xdg.desktopEntries = {
    xterm = {
      name = "XTerm (Hidden)";
      noDisplay = true;
    };
  };

  # (프리셋 mods는 flake.nix의 custom-iso extraModules에서 주입)
}
