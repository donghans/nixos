{
  pkgs,
  config,
  ...
}: {
  imports = [
    ./os/_optimize.nix
  ];

  # == User & Nix Engine ==
  users.users.${config.workspace.username} = {
    isNormalUser = true;
    extraGroups = ["wheel" "networkmanager"];
    shell = pkgs.zsh;
  };

  # (목적: root 포함 모든 계정에 Zsh 적용; 상세 설정은 Home Manager에서 처리)
  users.defaultUserShell = pkgs.zsh;
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
    hostName = config.workspace.hostname;
  };

  time.timeZone = "Asia/Seoul";
  i18n.defaultLocale = "en_US.UTF-8";
  i18n.supportedLocales = [
    "en_US.UTF-8/UTF-8"
    "ko_KR.UTF-8/UTF-8"
  ];

  environment.systemPackages = with pkgs; [
    git
    nano
    wget
    curl
    htop
  ];

  system.stateVersion = config.workspace.stateVersion;
}
