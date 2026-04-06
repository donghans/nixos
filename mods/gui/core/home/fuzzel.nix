# [working-refactor] 해당 구문은 before-refactor/lib/_base/hyprland.home/fuzzel.nix 에 있었음
# [working-refactor] 해당 구문은 after-refactor/... 로 들어가야 함
{hyprTerm, ...}: {
  programs.fuzzel.enable = true;

  programs.fuzzel.settings = {
    main = {
      font = "NanumGothicCoding:size=13";
      terminal = hyprTerm;
      width = 80;
      lines = 40;
      horizontal-pad = 20;
      dpi-aware = "no";
      show-icons = "yes";
      icon-theme = "Papirus-Dark";
    };

    colors = {
      background = "000000ff";
      text = "ffffffff";
      match = "cb4b16ff";
      selection = "268bd2ff";
      selection-text = "ffffffff";
      border = "002b36ff";
    };

    border = {
      width = 1;
      radius = 0;
    };
  };
}
