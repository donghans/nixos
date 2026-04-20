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

        # == Prompt Setup ==
        # (참고: root는 빨간색, 일반 유저는 초록색으로 구분됨)
        # (참고: 셸 환경 라인 — 중첩 깊이 / zsh 외 셸 이름 / nix 패키지)
        # (참고: git 라인 — 브랜치, 상태, push/pull, dirty, stash)

        # nix shell 감지용 베이스라인 PATH 저장 (최초 1회, 서브셸에 상속됨)
        [[ -z "$_ZSH_BASE_PATH" ]] && export _ZSH_BASE_PATH="$PATH"

        precmd() {
          local shell_parts=() git_parts=()

          # === 셸 환경 라인 ===

          # 중첩 깊이 + 셸 이름
          local env_parts=()
          local cur_shell
          cur_shell=$(cat /proc/$$/comm 2>/dev/null)
          cur_shell="''${cur_shell#-}"                       # 로그인 셸 앞의 - 제거
          [[ $SHLVL -gt 1 ]] && env_parts+=("%F{cyan}+$(( SHLVL - 1 ))%f")
          [[ -n "$cur_shell" && "$cur_shell" != "zsh" ]] && env_parts+=("%F{red}''${cur_shell}%f")
          [[ ''${#env_parts[@]} -gt 0 ]] && shell_parts+=("''${(j: :)env_parts}")

          # nix 패키지 (PATH의 /nix/store 직접 경로만 추출)
          local pkgs=() p name
          for p in ''${(s/:/)PATH}; do
            if [[ "$p" =~ ^/nix/store/[a-z0-9]{32}-.+/bin$ ]] && \
               [[ ":$_ZSH_BASE_PATH:" != *":$p:"* ]]; then
              name="''${p:44}"           # /nix/store/(11) + hash(32) + -(1) = 44자 건너뜀
              name="''${name%/bin}"      # /bin 제거
              name="''${name%%-[0-9]*}"  # 버전 제거: ripgrep-14.1.0 → ripgrep
              pkgs+=("%F{blue}''${name}%f")
            fi
          done
          [[ ''${#pkgs[@]} -gt 0 ]] && shell_parts+=("''${(j: :)pkgs}")

          # === git 라인 ===
          local branch
          branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
          if [[ -n "$branch" ]]; then
            git_parts+=("%F{yellow}''${branch}%f")

            # merge / rebase / cherry-pick 상태
            local git_dir
            git_dir=$(git rev-parse --git-dir 2>/dev/null)
            if   [[ -f "$git_dir/MERGE_HEAD"       ]]; then git_parts+=("%F{red}⊕M%f")
            elif [[ -d "$git_dir/rebase-merge"     ]]; then git_parts+=("%F{red}↺R%f")
            elif [[ -d "$git_dir/rebase-apply"     ]]; then git_parts+=("%F{red}↺R%f")
            elif [[ -f "$git_dir/CHERRY_PICK_HEAD" ]]; then git_parts+=("%F{red}◆C%f")
            fi

            # push/pull 커밋 수 (upstream 있을 때만)
            local ahead behind
            ahead=$(git rev-list --count @{u}..HEAD 2>/dev/null)
            behind=$(git rev-list --count HEAD..@{u} 2>/dev/null)
            (( ahead  > 0 )) && git_parts+=("%F{green}↑''${ahead}%f")
            (( behind > 0 )) && git_parts+=("%F{red}↓''${behind}%f")

            # dirty 상태
            local staged=0 unstaged=0 untracked=0 line
            while IFS= read -r line; do
              [[ "''${line[1]}" != " " && "''${line[1]}" != "?" ]] && (( staged++ ))
              [[ "''${line[2]}" == "M" || "''${line[2]}" == "D" ]] && (( unstaged++ ))
              [[ "''${line[1,2]}" == "??" ]] && (( untracked++ ))
            done < <(git status --porcelain 2>/dev/null)
            (( staged    > 0 )) && git_parts+=("%F{green}+''${staged}%f")
            (( unstaged  > 0 )) && git_parts+=("%F{yellow}!''${unstaged}%f")
            (( untracked > 0 )) && git_parts+=("%F{white}?''${untracked}%f")

            # stash 개수
            local stash_count=0
            while IFS= read -r _; do (( stash_count++ )); done < <(git stash list 2>/dev/null)
            (( stash_count > 0 )) && git_parts+=("%F{magenta}⚑''${stash_count}%f")
          fi

          # 프롬프트 조립 (있는 라인만 포함)
          local info=""
          [[ ''${#shell_parts[@]} -gt 0 ]] && info+=$'\n'"''${(j:  :)shell_parts}"
          [[ ''${#git_parts[@]} -gt 0 ]]   && info+=$'\n'"''${(j: :)git_parts}"

          PROMPT="''${info}"$'\n%B%F{%(#.red.green)}[%n@%m:%~]%(!.#.$) %f%b'
        }
        precmd  # 셸 시작 시 초기화

        # == Enable Colors for commands ==
        export CLICOLOR=1
        alias ls='ls --color=auto'
        alias grep='grep --color=auto'

        # == Key Bindings (단어 단위 이동: Ctrl+Arrow + Alt+Arrow 모두 허용) ==
        bindkey "^[[1;5C" forward-word   # Ctrl+Right
        bindkey "^[[1;5D" backward-word  # Ctrl+Left
        bindkey "^[[1;3C" forward-word   # Alt+Right (터미널 종류에 따라 Ctrl 대신 Alt로 전달됨)
        bindkey "^[[1;3D" backward-word  # Alt+Left
      ''
    ];
  };
}
