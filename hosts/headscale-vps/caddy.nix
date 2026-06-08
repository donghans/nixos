{config, ...}: let
  domain = config.headscale.domain;
in {
  services.caddy = {
    enable = true;
    globalConfig = ''
      email donghans@bitstep.it
    '';
    # GHA가 SCP로 배포하는 동적 vhost 파일 로드
    extraConfig = ''
      import /etc/caddy/sites/*.caddy
    '';
    virtualHosts.${domain}.extraConfig = ''
      reverse_proxy 127.0.0.1:8080
    '';
  };

  # admin 소유 → GHA가 SCP로 /etc/caddy/sites/landings.caddy 직접 배포 가능
  systemd.tmpfiles.rules = [
    "d /etc/caddy/sites 0755 admin root -"
  ];
}
