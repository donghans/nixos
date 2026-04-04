{
  pkgs,
  metaConfig,
  ...
}: {
  imports = [./nfd/_init.nix];

  # == User & Nix Engine ==
  users.users.${metaConfig.username} = {
    isNormalUser = true;
    extraGroups = ["wheel" "networkmanager"];
    shell = pkgs.zsh;
  };

  # (목적: root 계정에서도 편리한 관리 환경 제공)
  users.defaultUserShell = pkgs.zsh;

  programs.zsh = {
    enable = true;
    enableCompletion = true;
    autosuggestions.enable = true;
    syntaxHighlighting.enable = true;

    # == Syntax Highlighting Customization ==
    # (이유: 플러그인 로드 후 실행되도록 하단에 배치하여 'invalid subscript range' 오류 방지)
    promptInit = ''
      zsh-newuser-install() { : }

      # == Custom Styles (Must be defined after plugin load or handled safely) ==
      # NixOS의 programs.zsh.enableSyntaxHighlighting은 /etc/zshrc 마지막에 로드되므로
      # 여기에 직접 스타일을 정의하면 오류가 날 수 있습니다.
      # 따라서 훅(hook)을 사용하거나 로드 여부를 체크하여 안전하게 설정합니다.
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
    '';

    interactiveShellInit = ''
      # == Zsh Tab Completion Menu Selection ==
      zstyle ':completion:*' menu select

      # == Prompt Setup (Bash Style with User/Root Colors & Bold) ==
      PROMPT=$'\n%B%F{%(#.red.green)}[%n@%m:%~]%(!.#.$) %f%b'

      # == Enable Colors for commands ==
      export CLICOLOR=1
      alias ls='ls --color=auto'
      alias grep='grep --color=auto'
    '';
  };

  nix = {
    settings = {
      auto-optimise-store = true; # (목적: 중복 파일 자동 하드링크)
      max-jobs = "auto";
      trusted-users = ["root" "@wheel"];
      experimental-features = ["nix-command" "flakes"];
    };

    gc = {
      # (목적: 7일 이상 된 이전 세대 자동 정리)
      automatic = true;
      dates = "weekly";
      options = "--delete-older-than 7d";
    };
  };

  # == Networking & Localization ==
  networking = {
    networkmanager.enable = true;
    hostName = metaConfig.hostname;
  };

  # == File Management Infrastructure ==
  services.gvfs.enable = true; # (목적: 휴지통, SMB, 스마트폰 연결 지원)
  services.udisks2.enable = true; # (목적: 저장장치 마운트 관리 기반)

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

  # (목적: 부팅 시 온라인 대기 비활성화로 부팅 속도 향상)
  systemd.services.NetworkManager-wait-online.enable = false;
  systemd.network.wait-online.enable = false;

  time.timeZone = "Asia/Seoul";
  i18n.defaultLocale = "en_US.UTF-8";
  i18n.supportedLocales = [
    "en_US.UTF-8/UTF-8"
    "ko_KR.UTF-8/UTF-8"
  ];

  # 어디에서든 최소한 이 패키지들은 필요하다고 판단됨
  environment.systemPackages = with pkgs; [
    git
    nano
    wget
    curl
    htop
  ];

  # 이 설정 파일의 버전 (건드리지 마세요)
  system.stateVersion = metaConfig.stateVersion;
}
