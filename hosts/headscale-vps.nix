# Vultr 2GB — headscale 컨트롤 플레인
# EC2+Lightsail+S3 통합 대체 — nginx TLS 직접 종단, GitHub DB 백업
{mkHostConfiguration, ...}:
mkHostConfiguration (_: {
  os = {
    imports = [
      ./headscale-vps/headscale.nix
      ./headscale-vps/caddy.nix
      ./headscale-vps/github-backup.nix
      ./headscale-vps/docker.nix
    ];

    headscale.staticIpv4 = "141.164.59.97";

    networking.nameservers = ["1.1.1.1" "8.8.8.8"];
    services.resolved.extraConfig = "Cache=no-negative";

    # Vultr에는 보안그룹 없음 → NixOS 방화벽 직접 제어
    networking.firewall = {
      enable = true;
      allowedTCPPorts = [22 80 443];
      allowedUDPPorts = [3478]; # STUN
    };

    users.users.admin.openssh.authorizedKeys.keyFiles = [
      ./_deploy/headscale-vps.pub
    ];

    security.sudo.extraRules = [
      {
        users = ["admin"];
        commands = [
          {
            command = "ALL";
            options = ["NOPASSWD"];
          }
        ];
      }
    ];
  };
  hm = {};
})
