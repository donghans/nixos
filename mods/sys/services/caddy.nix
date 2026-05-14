{mkMod, ...}:
mkMod __curPos "Caddy Web Server with reverse proxy support" ({
  cfg,
  lib,
  ...
}: {
  options = {
    configText = lib.mkOption {
      type = lib.types.lines;
      default = "";
      description = "Extra Caddyfile configuration appended to the global config";
    };
    reloadUser = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "User allowed to run 'systemctl reload caddy' without a password";
    };
  };
  os = lib.mkMerge [
    {
      services.caddy = {
        enable = true;
        # /etc/caddy/sites/*.caddy 는 외부 배포 스크립트가 동적으로 추가하는 vhost 파일
        extraConfig = ''
          import /etc/caddy/sites/*.caddy
          ${cfg.configText}
        '';
      };
      # /etc/caddy/sites/ 은 NixOS가 관리하지 않는 동적 vhost 파일 보관 디렉터리
      # reloadUser가 설정되면 해당 유저가 직접 SCP로 파일을 배포할 수 있도록 소유권 부여
      systemd.tmpfiles.rules = [
        "d /etc/caddy/sites 0755 ${
          if cfg.reloadUser != null
          then cfg.reloadUser
          else "root"
        } root -"
      ];
      networking.firewall.allowedTCPPorts = [80 443];
    }
    (lib.mkIf (cfg.reloadUser != null) {
      security.sudo.extraRules = [
        {
          users = [cfg.reloadUser];
          commands = [
            {
              command = "/run/current-system/sw/bin/systemctl reload caddy.service";
              options = ["NOPASSWD"];
            }
          ];
        }
      ];
    })
  ];
})
