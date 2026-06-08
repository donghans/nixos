{...}: {
  virtualisation.docker.enable = true;
  virtualisation.docker.autoPrune.enable = true;
  virtualisation.docker.daemon.settings.dns = ["8.8.8.8" "8.8.4.4"];
  users.users.admin.extraGroups = ["docker"];

  # Docker 28+는 iptables 대신 nftables로 NAT 관리
  networking.nftables.enable = true;

  # systemd-networkd가 Docker veth/브리지를 가로채 br-*가 NO-CARRIER 되는 현상 방지
  # ref: mods/sys/services/docker.nix
  systemd.network.networks."20-docker-veth" = {
    matchConfig.Name = "veth* br-* docker*";
    linkConfig.Unmanaged = true;
  };

  systemd.tmpfiles.rules = [
    "d /home/admin/landings 0755 admin users -"
  ];
}
