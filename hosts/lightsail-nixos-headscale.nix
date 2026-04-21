# lightsail-nixos-headscale 호스트 설정
# SSH 공개키는 hosts/pubs/lightsail-nixos-headscale.pub 에서 자동 로드됩니다.
{mkHostConfiguration, ...}:
mkHostConfiguration (_: {
  os = {
    # == headscale 서비스 설정 ==
    # services.headscale.enable = true;
    # services.headscale.settings = {
    #   server_url = "https://HEADSCALE_DOMAIN";
    #   listen_addr = "127.0.0.1:8080";
    #   grpc_listen_addr = "127.0.0.1:50443";
    #   metrics_listen_addr = "127.0.0.1:9090";
    #   log.level = "info";
    #   dns = {
    #     magic_dns = true;
    #     base_domain = "headscale.local";
    #     nameservers.global = ["1.1.1.1" "8.8.8.8"];
    #   };
    # };

    # == Caddy reverse proxy ==
    # services.caddy.extraConfig = ''
    #   HEADSCALE_DOMAIN {
    #     reverse_proxy /web* localhost:80
    #     reverse_proxy * localhost:8080
    #   }
    # '';
  };
})
