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
}
