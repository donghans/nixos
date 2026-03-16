# 1. 함수의 시작: 시스템 구성에 필요한 도구들을 인자로 받습니다.
{ config, pkgs, metaConfig, ... }:

{
  imports = [
    ./.hardware.nix
    ../../lib/hyprland.nix
  ];

  # 메모리 최적화 (zram)
  zramSwap = {
    enable = true;
    algorithm = "zstd";
    memoryPercent = 50;
    priority = 100;
  };

  boot.tmp.useTmpfs = true;
  boot.tmp.tmpfsSize = "50%";

  # Snapper 설정 (시스템 서비스) TODO 적절한 백업 주기 및 서브볼륨 분리할 것
  # services.snapper = {
  #   snapshotInterval = "hourly"; # 기본 주기
  #   configs = {
  #     home = {
  #       SUBVOLUME = "/home";
  #       TIMELINE_CREATE = true;
  #       TIMELINE_CLEANUP = true;
  #     };
  #     # 앞서 논의한 Downloads 전용 설정 등 추가 가능
  #   };
  # };

  # (선택사항) btrbk 설정
  # services.btrbk.instances."local" = { ... };

  services.tailscale.enable = true;

  virtualisation.docker = {
    enable = true;
    autoPrune.enable = true;
  };

  # 사용자 계정
  users.users.${metaConfig.username} = {
    isNormalUser = true;
    extraGroups = [ "wheel" "networkmanager" "adbusers" "docker" ];
  };

  # 1. nix-ld 활성화
  programs.nix-ld.enable = true;

  # 2. FVM/Flutter 바이너리가 참조할 라이브러리 목록
  programs.nix-ld.libraries = with pkgs; [
    # 필수 기본 라이브러리
    stdenv.cc.cc
    zlib
    fuse3
    icu
    nss
    openssl
    curl
    expat

    # Flutter GUI / 그래픽 관련
    libGL
    glib
    gtk3
    cairo
    pango
    atk
    gdk-pixbuf
    harfbuzz
    fontconfig
    freetype

    # X11 / Wayland 관련 (JetBrains와 Hyprland 환경 대응)
    # libX11
    # libXcomposite
    # libXcursor
    # libXdamage
    # libXext
    # libXfixes
    # libXi
    # libXrender
    # libXtst
    # libXrandr
    # libXScrnSaver
    # libxcb
    # libxkbcommon
    wayland

    # 오디오 및 기타 미디어
    alsa-lib
    libpulseaudio
    dbus
    libdrm
    mesa
    libnotify
  ];

  # 3. FVM을 시스템 패키지에 추가 (선택 사항)
  environment.systemPackages = with pkgs; [
    fvm
    unzip
  ];
}
