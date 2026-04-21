# AWS Lightsail headscale 서버 호스트 설정
# 부트로더/파티션: core.boot.nix + disko.nix가 bootTarget="cloud-bios" 기반으로 자동 처리
# 배포 전 HEADSCALE_DOMAIN을 실제 도메인으로 교체하세요.
{mkHostConfiguration, ...}:
mkHostConfiguration (_: {
  os = {
    # == SSH 공개키 (rnixstrap이 .pem에서 추출하여 여기에 직접 기재) ==
    # 실제 배포 전 rnixstrap을 실행하면 이 파일이 자동으로 갱신됩니다.
    users.users.root.openssh.authorizedKeys.keys = [
      # ssh-keygen -y -f lightsail-headscale.pem
    ];

    # == headscale 서비스 설정 ==
    services.headscale.enable = true;
    services.headscale.settings = {
      server_url = "https://HEADSCALE_DOMAIN";
      listen_addr = "127.0.0.1:8080";
      grpc_listen_addr = "127.0.0.1:50443";
      metrics_listen_addr = "127.0.0.1:9090";
      log.level = "info";
      dns = {
        magic_dns = true;
        base_domain = "headscale.local";
        nameservers.global = ["1.1.1.1" "8.8.8.8"];
      };
    };

    # == Caddy reverse proxy ==
    services.caddy.extraConfig = ''
      HEADSCALE_DOMAIN {
        reverse_proxy /web* localhost:80
        reverse_proxy * localhost:8080
      }
    '';
  };
})
