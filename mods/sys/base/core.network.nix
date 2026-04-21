{mkPartOf, ...}:
mkPartOf "mods.sys.base" ({
  config,
  pkgs,
  lib,
  ...
}: let
  useNM = config.workspace.type == "desktop" || config.workspace.type == "laptop";
in {
  os = lib.mkMerge [
    # Desktop / Laptop → NetworkManager
    (lib.mkIf useNM {
      networking.networkmanager.enable = true;
      networking.useDHCP = false;
      # (목적: NM 온라인 대기 비활성화로 부팅 속도 향상)
      systemd.services.NetworkManager-wait-online.enable = false;
      # (목적: nmcli 및 nm-applet 사용에 필요한 그룹 멤버십)
      users.users.${config.workspace.username}.extraGroups = ["networkmanager"];
    })
    # Server / RPi → systemd-networkd
    (lib.mkIf (!useNM) {
      networking.useNetworkd = true;
      networking.useDHCP = false;
      services.resolved.enable = true;
      # (목적: 온라인 대기 비활성화로 부팅 속도 향상)
      systemd.network.wait-online.enable = false;
      # (목적: eth0/ens5 등 이름 무관하게 이더넷 인터페이스 DHCP 자동 설정)
      systemd.network.networks."10-ethernet" = {
        matchConfig.Type = "ether";
        networkConfig.DHCP = "ipv4";
      };
    })
  ];

  # (목적: GUI 환경에서 NM 트레이 아이콘 실행)
  hm = lib.mkIf (useNM && config.mods.gui.enable) {
    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 500 [
      "uwsm app -- ${pkgs.networkmanagerapplet}/bin/nm-applet"
    ];
  };
})
