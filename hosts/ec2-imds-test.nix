# EC2 IMDS / IAM Instance Profile 동작 확인용 최소 호스트
# 검증 항목:
#   1. IMDSv2 라우트 (169.254.169.254/32) NixOS systemd-networkd에서 접근 가능
#   2. IAM Instance Profile → AWS 자격증명 체인 (aws sts get-caller-identity)
#   3. S3 권한 확인 (aws s3 ls s3://<버킷명>)
# 확인 완료 후 ec2-nixos-headscale로 전환
{ mkHostConfiguration, pkgs, lib, ... }:
mkHostConfiguration (_: {
  os = {
    # IMDSv2 링크 라우트 — Instance Profile 접근에 필수
    systemd.network.networks."05-ens5" = {
      matchConfig.Name = "ens5";
      networkConfig.DHCP = "ipv4";
      routes = [{ Destination = "169.254.169.254/32"; Scope = "link"; }];
      dhcpV4Config.UseDNS = false;
    };
    networking.nameservers = [ "1.1.1.1" "8.8.8.8" ];
    services.resolved.extraConfig = "Cache=no-negative";

    # EC2 보안그룹이 외부 트래픽 제어
    networking.firewall.enable = false;

    # SSM Session Manager — Instance Profile 자동 인증, SSH 없이 접속 가능
    services.amazon-ssm-agent.enable = true;

    # 테스트 도구
    environment.systemPackages = [ pkgs.awscli2 pkgs.curl ];
  };
  hm = {};
})
