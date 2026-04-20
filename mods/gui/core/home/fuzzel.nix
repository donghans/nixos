{mkMod, ...}:
mkMod __curPos null ({config, ...}: {
  hm = {
    programs.fuzzel.enable = true;

    programs.fuzzel.settings = {
      main = {
        font = "NanumGothicCoding:size=13";
        # hyprTerm은 _module.args로 전달되나 innerModule의 named arg로 받으면
        # 함수 호출 시 key set 강제평가로 순환 참조 발생 → config로 lazily 접근
        terminal = config._module.args.hyprTerm;
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
  };
})
