{
  pkgs,
  metaConfig,
  ...
}: {
  imports = [
    ./default/_optimize.nix
    ./default/nfd.nix
  ];

  # == User & Nix Engine ==
  users.users.${metaConfig.username} = {
    isNormalUser = true;
    extraGroups = ["wheel" "networkmanager"];
    shell = pkgs.zsh;
  };

  # (목적: root 계정에서도 편리한 관리 환경 제공)
  users.defaultUserShell = pkgs.zsh;

  # 시스템 레벨에서는 Zsh를 사용 가능하게만 설정 (상세 설정은 Home Manager에서 처리)
  programs.zsh.enable = true;

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
