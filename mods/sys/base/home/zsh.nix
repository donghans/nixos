{lib, ...}: {
  programs.zsh = {
    enable = true; # (목적: 사용자별 .zshrc를 생성하여 초기 설치 메시지 차단)
    enableCompletion = true;
    autosuggestion.enable = true;
    syntaxHighlighting.enable = true;

    # == Zsh Initialization (initContent replaces deprecated initExtra/First) ==
    initContent = lib.mkMerge [
      # == Syntax Highlighting Customization (Top of .zshrc) ==
      (lib.mkBefore ''
        zsh-newuser-install() { : }

        # == Custom Styles ==
        # (목적: 명령어나 경로 색상을 간결하게 유지하고 오류만 강조)
        typeset -gA ZSH_HIGHLIGHT_STYLES
        ZSH_HIGHLIGHT_STYLES[command]='none'
        ZSH_HIGHLIGHT_STYLES[precommand]='none'
        ZSH_HIGHLIGHT_STYLES[alias]='none'
        ZSH_HIGHLIGHT_STYLES[builtin]='none'
        ZSH_HIGHLIGHT_STYLES[function]='none'
        ZSH_HIGHLIGHT_STYLES[commandseparator]='none'
        ZSH_HIGHLIGHT_STYLES[path]='none'
        ZSH_HIGHLIGHT_STYLES[path_prefix]='none'
        ZSH_HIGHLIGHT_STYLES[unknown-token]='fg=red,bold'
      '')

      # == Interactive Shell Logic (Standard content) ==
      ''
        # == Autosuggestions Style ==
        export ZSH_AUTOSUGGEST_HIGHLIGHT_STYLE="fg=8"

        # == Smart Tab Binding ==
        # (목적: 제안이 있으면 Tab으로 즉시 수락, 없으면 표준 자동완성 실행)
        _smart_tab() {
          if [[ -n "$POSTDISPLAY" ]]; then
            zle autosuggest-accept
          else
            zle expand-or-complete
          fi
        }
        zle -N _smart_tab
        bindkey '^I' _smart_tab

        # == Zsh Tab Completion Menu Selection ==
        zstyle ':completion:*' menu select

        # == Prompt Setup (Bash Style with User/Root Colors & Bold) ==
        # (참고: root는 빨간색, 일반 유저는 초록색으로 구분됨)
        PROMPT=$'\n%B%F{%(#.red.green)}[%n@%m:%~]%(!.#.$) %f%b'

        # == Enable Colors for commands ==
        export CLICOLOR=1
        alias ls='ls --color=auto'
        alias grep='grep --color=auto'

        # == LLM CLI Compatibility (Gemini Home/End Fix) ==
        # (목적: Node.js 기반 CLI가 xterm-kitty 시퀀스를 인식 못할 때 표준 xterm으로 강제)
        if command -v gemini-cli >/dev/null 2>&1; then
          alias gemini='TERM=xterm-256color gemini-cli'
        fi

        # == Key Bindings (단어 단위 이동 및 홈/엔드) ==
        # (목적: 다양한 터미널 환경에서 일관된 키 동작 보장)
        bindkey "^[[H" beginning-of-line      # Home (Standard)
        bindkey "^[[F" end-of-line            # End (Standard)
        bindkey "^[OH" beginning-of-line      # Home (Alternative)
        bindkey "^[OF" end-of-line            # End (Alternative)
        bindkey "^[[1~" beginning-of-line     # Home (Xterm)
        bindkey "^[[4~" end-of-line           # End (Xterm)
        bindkey "^[[3~" delete-char           # Delete (Standard)

        bindkey "^[[1;5C" forward-word        # Ctrl+Right
        bindkey "^[[1;5D" backward-word       # Ctrl+Left
        bindkey "^[[1;3C" forward-word        # Alt+Right (Meta+Right)
        bindkey "^[[1;3D" backward-word       # Alt+Left (Meta+Left)
      ''
    ];
  };
}
