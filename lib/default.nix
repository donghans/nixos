{
  pkgs,
  metaConfig,
  ...
}: {
  # == User & Nix Engine ==
  users.users.${metaConfig.username} = {
    isNormalUser = true;
    extraGroups = ["wheel" "networkmanager"];
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
