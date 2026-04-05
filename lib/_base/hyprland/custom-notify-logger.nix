{
  pkgs,
  lib,
  config,
  ...
}:
with lib; let
  cfg = config.services.custom-notify-logger;

  # 로그 기록용 스크립트 분리
  logger-script = pkgs.writeShellScript "custom-notify-logger-script" ''
    set -euo pipefail

    # systemd --user 환경에서는 $USER 변수가 주입됨
    LOG_DIR="/var/log/notify-logger"
    LOG_PATH="$LOG_DIR/history-''${USER}.log"

    # stdbuf -oL을 사용하여 라인 버퍼링 강제 (실시간 기록 핵심)
    count=0
    summary=""
    body=""

    ${pkgs.coreutils}/bin/stdbuf -oL ${pkgs.dbus}/bin/dbus-monitor "interface='org.freedesktop.Notifications',member='Notify',type='method_call'" | \
    while read -r line; do
      if echo "$line" | grep -q "member=Notify"; then
        count=0
        summary=""
        body=""
      fi

      if echo "$line" | grep -q 'string "'; then
        count=$((count + 1))
        content=$(echo "$line" | sed 's/.*string "\(.*\)".*/\1/')

        if [ $count -eq 3 ]; then
          summary="$content"
        elif [ $count -eq 4 ]; then
          body="$content"
          if [ -n "$summary" ]; then
            echo "[$(date +'%Y-%m-%d %H:%M:%S')] [$summary] $body" >> "$LOG_PATH"
            count=99
          fi
        fi
      fi
    done
  '';
in {
  options.services.custom-notify-logger = {
    enable = mkOption {
      type = types.bool;
      default = true;
      description = "Notification Logger Service를 활성화합니다.";
    };
  };

  config = mkIf cfg.enable {
    # 1. 전역 로그 디렉터리 생성 (다중 사용자 환경 지원을 위해 Sticky Bit 적용)
    systemd.tmpfiles.rules = [
      "d /var/log/notify-logger 1777 root root -"
    ];

    # 2. 사용자별 시스템디 서비스 등록 (NixOS 레벨에서도 systemd.user.services 정의 가능)
    systemd.user.services.custom-notify-logger = {
      description = "Notification Logger Service";
      wantedBy = ["graphical-session.target"];
      after = ["graphical-session-pre.target"];
      partOf = ["graphical-session.target"];
      serviceConfig = {
        ExecStart = "${logger-script}";
        Restart = "always"; # 죽으면 다시 살림
        RestartSec = 3;
      };
    };

    # 3. 전역 Logrotate 설정 (NixOS 레벨)
    services.logrotate.settings."custom-notify-logger" = {
      files = "/var/log/notify-logger/history-*.log";
      frequency = "daily";
      rotate = 30;
      delaycompress = true;
      missingok = true;
      notifempty = true;
      create = "0644 root root";
      su = "root root";
    };
  };
}
