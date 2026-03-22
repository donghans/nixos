{ pkgs, metaConfig, ... }: {
  # 사용자 계정
  users.users.${metaConfig.username} = {
    isNormalUser = true;
    extraGroups = [ "wheel" "networkmanager" ];
  };

  programs.nix-ld.enable = true;

  nixpkgs = {
    config.allowUnfree = true;

    overlays = [
      (self: super: {
        mkNixLDWrapper = pkg: libs: super.symlinkJoin {
          name = "${pkg.name}-nix-ld";
          paths = [ pkg ];
          nativeBuildInputs = [ super.makeWrapper ];
          postBuild = ''
            for bin in $out/bin/*; do
              wrapProgram "$bin" \
                --set NIX_LD_LIBRARY_PATH "${super.lib.makeLibraryPath libs}" \
                --set NIX_LD "${super.stdenv.cc.bintools.dynamicLinker}"
            done
          '';
        };
      })
    ];
  };

  nix = {
    settings = {
      auto-optimise-store = true; # Nixpkgs 등의 중복 파일 자동 하드링크
      max-jobs = "auto"; # Nix 빌드 시 CPU를 얼마나 굴릴건지에 대한 설정
      trusted-users = [ "root" "@wheel" ];

      # Nix flake 기능 허용
      # Nixpkgs 상태(각 패키지의 마이너버전 등)부터 NixOS 설치/빌드를 위한 모든 정보를 재현가능한 수준으로 고정시키는 도구
      experimental-features = [ "nix-command" "flakes" ];
    };

    gc = { # Nix 제네레이션(스냅샷, 복원포인트) 정리(제거) 설정, (= Garbage Collection)
      automatic = true;
      dates = "weekly";
      options = "--delete-older-than 7d";
    };
  };

  # 무겁지만 기기별 호환성 안타고 쉽게 유선 LAN 및 무선 Wi-Fi를 사용 가능한 NetworkManager(nmcli) 사용
  networking.networkmanager.enable = true;
  networking.hostName = metaConfig.hostname;

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
