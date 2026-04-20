{mkPartOf, ...}:
mkPartOf "mods.sys.base" ({lib, ...}: {
  hm = {
    programs.zsh = {
      enable = true; # (목적: 사용자별 .zshrc를 생성하여 초기 설치 메시지 차단)
      enableCompletion = true;
      autosuggestion.enable = true;
      syntaxHighlighting.enable = true;

      # == Zsh Initialization (initContent replaces deprecated initExtra/First) ==
      initContent = lib.mkMerge [
        # Syntax Highlighting 커스터마이징 (최상단 배치) — mods/_data/zsh/init.pre.zsh
        (lib.mkBefore (builtins.readFile ../../_data/zsh/init.pre.zsh))
        # 인터랙티브 셸 초기화 — mods/_data/zsh/init.zsh
        (builtins.readFile ../../_data/zsh/init.zsh)
      ];
    };
  };
})
