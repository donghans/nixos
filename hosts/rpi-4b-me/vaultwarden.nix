{pkgs, ...}: {
  services.vaultwarden = {
    enable = true;
    config = {
      ROCKET_PORT = 8000;
      SIGNUPS_ALLOWED = false;
    };
  };

  # Litestream 백업 서비스 설정
  services.litestream = {
    enable = true;
    settings = {
      dbs = [
        {
          path = "/var/lib/vaultwarden/db.sqlite3";
          replicas = [
            {
              url = "s3://8031cf356a347a425d9f7bc457be6b48c45e2a2c5aacebe296c47e301981085/1";
              retention = "90d";
              "snapshot-interval" = "24h";
            }
          ];
        }
      ];
    };
  };

  # Litestream 백업 서비스에 환경변수 파일 추가
  systemd.services.litestream.serviceConfig.EnvironmentFile = "/etc/litestream.env";

  # S3로부터 안전 복원을 수행하는 일회성 서비스 유닛 생성
  systemd.services.litestream-restore = {
    description = "Restore SQLite DB from S3 before backup or app start";
    wantedBy = ["multi-user.target"];
    before = ["vaultwarden.service" "litestream.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      EnvironmentFile = "/etc/litestream.env";
      User = "root"; # 디렉토리 생성 및 소유권 변경을 위해 root로 실행
    };
    script = ''
      mkdir -p /var/lib/vaultwarden
      if [ ! -f /var/lib/vaultwarden/db.sqlite3 ]; then
        if [ -s /etc/litestream.env ]; then
          echo "No database found. Running litestream restore from S3..."
          ${pkgs.litestream}/bin/litestream restore -if-db-not-exists -o /var/lib/vaultwarden/db.sqlite3 s3://8031cf356a347a425d9f7bc457be6b48c45e2a2c5aacebe296c47e301981085/1

          # 소유권과 권한을 vaultwarden 계정으로 교정
          chown -R vaultwarden:vaultwarden /var/lib/vaultwarden || true
          chmod 700 /var/lib/vaultwarden || true
          if [ -f /var/lib/vaultwarden/db.sqlite3 ]; then
            chown vaultwarden:vaultwarden /var/lib/vaultwarden/db.sqlite3 || true
            chmod 600 /var/lib/vaultwarden/db.sqlite3 || true
          fi
          echo "Restore process completed."
        else
          echo "Error: /etc/litestream.env is missing or empty. Cannot restore database!"
          exit 1 # 시크릿 주입 전에 백업/앱이 시작되는 걸 막기 위해 실패 처리
        fi
      else
        echo "Database already exists. Skipping restore to prevent overwriting."
      fi
    '';
  };

  # Vaultwarden과 Litestream 백업 서비스가 복원 작업 완료 후에만 시작하도록 의존성 주입
  systemd.services.vaultwarden = {
    requires = ["litestream-restore.service"];
    after = ["litestream-restore.service"];
  };

  systemd.services.litestream = {
    requires = ["litestream-restore.service"];
    after = ["litestream-restore.service"];
  };

  # 방화벽 허용 포트 설정 (Vaultwarden: 8000)
  networking.firewall.allowedTCPPorts = [8000];
}
