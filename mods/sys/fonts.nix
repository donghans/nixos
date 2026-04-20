{mkModHere, ...}:
mkModHere __curPos "CJK and Nerd Fonts" ({pkgs, ...}: {
  os = {
    fonts = {
      packages = with pkgs; [
        nanum
        nanum-gothic-coding
        noto-fonts-cjk-sans
        noto-fonts-cjk-serif
        noto-fonts-color-emoji
      ];
      fontconfig.defaultFonts = {
        serif = ["NanumMyeongjo" "Noto Serif CJK KR"];
        sansSerif = ["NanumGothic" "Noto Sans CJK KR"];
        monospace = ["NanumGothicCoding"];
        emoji = ["Noto Color Emoji"];
      };
    };

    # == TTY Unicode & Font Support ==
    services.kmscon = {
      enable = true;
      hwRender = true; # (이유: 하드웨어 가속 활용)
      fonts = [
        {
          name = "NanumGothicCoding";
          package = pkgs.nanum-gothic-coding;
        }
      ];
      extraConfig = "font-size=14"; # (이유: TTY 가독성 향상)
    };
  };
  hm = {
    home.packages = with pkgs; [
      nanum
      nanum-gothic-coding
      noto-fonts-cjk-sans
      noto-fonts-cjk-serif
      noto-fonts-color-emoji
    ];
  };
})
