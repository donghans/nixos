{config, ...}: let
  domain = config.headscale.domain;
in {
  services.caddy = {
    enable = true;
    globalConfig = ''
      email donghans@bitstep.it
    '';
    virtualHosts.${domain}.extraConfig = ''
      reverse_proxy 127.0.0.1:8080
    '';
  };
}
