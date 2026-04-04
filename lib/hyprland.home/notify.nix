{
  pkgs,
  lib,
  config,
  ...
}:
with lib; let
  cfg = config.services.my-notification-logger;

  # 로그 기록용 스크립트 분리
  logger-script = pkgs.writeShellScript "notify-logger-script" ''
    set -euo pipefail

    # 로그 디렉토리 생성
    mkdir -p "$(dirname "${cfg.logPath}")"

    # stdbuf -oL을 사용하여 라인 버퍼링 강제 (실시간 기록 핵심)
    ${pkgs.coreutils}/bin/stdbuf -oL ${pkgs.dbus}/bin/dbus-monitor "interface='org.freedesktop.Notifications',member='Notify'" | \
    while read -r line; do
      if echo "$line" | grep -q "member=Notify"; then
        count=0
        summary=""
        body=""
      fi

      if echo "$line" | grep -q 'string "'; then
        count=$((count + 1))
        # sed 결과도 즉시 반영되도록 처리
        content=$(echo "$line" | sed 's/.*string "\(.*\)".*/\1/')

        if [ $count -eq 3 ]; then
          summary="$content"
        elif [ $count -eq 4 ]; then
          body="$content"
          if [ -n "$summary" ]; then
            echo "[$(date +'%Y-%m-%d %H:%M:%S')] [$summary] $body" >> "${cfg.logPath}"
            count=99
          fi
        fi
      fi
    done
  '';
in {
  options.services.my-notification-logger = {
    enable = mkEnableOption "Notification Logger Service";
    logPath = mkOption {
      type = types.str;
      default = "${config.home.homeDirectory}/.local/share/notify.log";
      description = "알림 로그가 저장될 경로입니다.";
    };
  };

  config = mkIf cfg.enable {
    # 1. 시스템디 사용자 서비스 등록
    systemd.user.services.my-notification-logger = {
      Unit = {
        Description = "Notification Logger Service";
        After = ["graphical-session-pre.target"];
        PartOf = ["graphical-session.target"];
      };
      Service = {
        ExecStart = "${logger-script}";
        Restart = "always"; # 죽으면 다시 살림
        RestartSec = 3;
      };
      Install = {
        WantedBy = ["graphical-session.target"];
      };
    };

    # 2. Logrotate 설정 (기존과 동일)
    systemd.user.services.notify-logrotate = {
      Unit = {Description = "Rotate notification logs";};
      Service = {
        ExecStart = let
          logrotateConf = pkgs.writeText "notify-logrotate.conf" ''
            "${cfg.logPath}" {
              daily
              rotate 30
              delaycompress
              missingok
              notifempty
              create 0644
            }
          '';
        in "${pkgs.logrotate}/bin/logrotate --state ${config.home.homeDirectory}/.local/share/logrotate.state ${logrotateConf}";
      };
    };

    systemd.user.timers.notify-logrotate = {
      Unit = {Description = "Daily rotation of notification logs";};
      Timer = {
        OnCalendar = "daily";
        Persistent = true;
      };
      Install = {WantedBy = ["timers.target"];};
    };
  };
}
