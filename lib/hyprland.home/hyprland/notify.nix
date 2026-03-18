{ pkgs, lib, config, ... }:
with lib;
let
  cfg = config.services.my-notification-logger;
in {
  options.services.my-notification-logger = {
    enable = mkEnableOption "Notification Logger Service";
    logPath = mkOption {
      type = types.str;
      # 기본값 설정
      default = "${config.home.homeDirectory}/.local/share/notify.log";
      description = "알림 로그가 저장될 경로입니다.";
    };
  };

  config = mkIf cfg.enable {
    # 1. 스크립트 정의 및 패키지 추가
    home.packages = [
      (pkgs.writeShellScriptBin "notify-logger" ''
        # cfg.logPath를 사용합니다.
        mkdir -p $(dirname "${cfg.logPath}")

        ${pkgs.dbus}/bin/dbus-monitor "interface='org.freedesktop.Notifications',member='Notify'" | \
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
                # cfg.logPath에 기록
                echo "[$(date +'%Y-%m-%d %H:%M:%S')] [$summary] $body" >> "${cfg.logPath}"
                count=99
              fi
            fi
          fi
        done
      '')
    ];

    # 2. logrotate 설정 (config 블록 안으로 이동시켜 cfg 참조를 확실히 함)
    systemd.user.services.notify-logrotate = let
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
    in {
      Unit = { Description = "Rotate notification logs"; };
      Service = {
        ExecStart = "${pkgs.logrotate}/bin/logrotate --state ${config.home.homeDirectory}/.local/share/logrotate.state ${logrotateConf}";
      };
    };

    # 3. 타이머 설정
    systemd.user.timers.notify-logrotate = {
      Unit = { Description = "Daily rotation of notification logs"; };
      Timer = {
        OnCalendar = "daily";
        Persistent = true;
      };
      Install = { WantedBy = [ "timers.target" ]; };
    };
  };
}
