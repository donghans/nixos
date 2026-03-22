# 1. 함수의 시작: 시스템 구성에 필요한 도구들을 인자로 받습니다.
{ config, metaConfig, ... }: {
  imports = [
    ./_filesystem.nix
    ../../lib/hyprland.nix
  ];

  services.tailscale.enable = true;

  virtualisation.docker = {
    enable = true;
    autoPrune.enable = true;
  };

  programs.adb.enable = true;
  networking.firewall.allowedUDPPorts = [ 5353 ]; # ADB 기기 검색(mDNS)

  # 사용자 계정
  users.users.${metaConfig.username} = {
    extraGroups = [ "adbusers" "docker" ];
  };
}
