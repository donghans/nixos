# EC2 t4g.micro headscale 컨트롤 플레인
# lightsail-nixos-headscale.nix 대체 — step-ca / Roles Anywhere 제거
# AWS 인증: IAM Instance Profile (EC2 전용, 자동)
# DB 백업: litestream → S3 (Instance Profile 자격증명 사용)
{mkHostConfiguration, ...}:
mkHostConfiguration (_: {
  os = {
    imports = [
      ./ec2-nixos-headscale/headscale.nix
      ./ec2-nixos-headscale/eni-forwarding.nix
      ./ec2-nixos-headscale/lightsail-proxy.nix
      ./ec2-nixos-headscale/github-backup.nix
    ];

    # == EC2 네트워크 설정 ==
    # IMDS 라우트는 DHCP가 자동 처리 — 별도 설정 불필요
    networking.nameservers = ["1.1.1.1" "8.8.8.8"];
    services.resolved.extraConfig = "Cache=no-negative";

    # EC2 보안그룹이 외부 트래픽 제어 — NixOS 방화벽 비활성화
    networking.firewall.enable = false;

    systemd.tmpfiles.rules = ["d /opt/landings 0755 ec2-user users -"];

    # SSH 접근: nixos-anywhere 재설치 후 cloud-init 없이도 키 유지
    users.users.ec2-user.openssh.authorizedKeys.keyFiles = [
      ./_deploy/ec2-nixos-headscale.pub
    ];

    # deploy-rs: ec2-user로 SSH → root로 sudo 실행 (nixos activation용)
    security.sudo.extraRules = [
      {
        users = ["ec2-user"];
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
