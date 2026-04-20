{
  mkModHere,
  lib,
  ...
}: let
  base = mkModHere __curPos "Custom Notification Logger" ({
    cfg,
    config,
    pkgs,
    lib,
    ...
  }: let
    svcCfg = config.services.custom-notify-logger;

    logger-script = pkgs.writers.writePython3 "custom-notify-logger-script" {} ''
      import datetime
      import os
      import re
      import subprocess

      log_dir = os.environ["LOG_DIR"]
      user = os.environ.get("USER", "unknown")
      log_path = os.path.join(log_dir, f"{user}.log")


      def parse_string_value(line):
          m = re.match(r'\s+string "(.*)"$', line)
          return m.group(1) if m else None


      # stdbuf -oL: 라인 버퍼링 강제 (실시간 기록 핵심)
      # fmt: off
      _stdbuf = "${pkgs.coreutils}/bin/stdbuf"  # noqa: E501
      _dbus_mon = "${pkgs.dbus}/bin/dbus-monitor"  # noqa: E501
      # fmt: on
      _dbus_filter = (
          "interface='org.freedesktop.Notifications',"
          "member='Notify',type='method_call'"
      )
      proc = subprocess.Popen(
          [_stdbuf, "-oL", _dbus_mon, _dbus_filter],
          stdout=subprocess.PIPE,
          text=True,
          bufsize=1,
      )

      strings_in_block = []
      in_notify_block = False

      for raw_line in proc.stdout:
          line = raw_line.rstrip("\n")

          if "member=Notify" in line:
              strings_in_block = []
              in_notify_block = True
              continue

          if not in_notify_block:
              continue

          # 들여쓰기 없는 라인 = 새 메시지 헤더 → 블록 종료
          if line and not line[0].isspace():
              in_notify_block = False
              strings_in_block = []
              continue

          val = parse_string_value(line)
          if val is not None:
              strings_in_block.append(val)

              # dbus Notify 시그니처:
              # s(0:app_name) s(1:app_icon) u(skip) s(2:summary) s(3:body) ...
              # uint32/array/dict 라인은 parse_string_value가 None 반환 → 자동 무시
              if len(strings_in_block) == 4:
                  app_name = strings_in_block[0]
                  summary = strings_in_block[2]
                  body = strings_in_block[3]
                  if summary:
                      ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                      with open(log_path, "a", encoding="utf-8") as f:
                          f.write(f"[{ts}] [{app_name}] [{summary}] {body}\n")
                  in_notify_block = False
                  strings_in_block = []
    '';
  in {
    os = lib.mkMerge [
      # cfg.enable → svcCfg.enable 캐스케이드 (NixOS 컨텍스트)
      {services.custom-notify-logger.enable = lib.mkDefault true;}

      (lib.mkIf svcCfg.enable {
        # 전역 로그 디렉터리 생성 (Sticky Bit + 실행 권한만 부여 → 타 사용자 파일 목록 열람 차단)
        systemd.tmpfiles.rules = [
          "d ${svcCfg.logDir} 1777 root root -"
        ];

        # 전역 Logrotate 설정 (NixOS 레벨)
        services.logrotate.settings."custom-notify-logger" = {
          files = "${svcCfg.logDir}/*.log";
          frequency = "daily";
          rotate = 30;
          delaycompress = true;
          missingok = true;
          notifempty = true;
          nocreate = true;
          su = "root root";
        };

        # NixOS systemd 모듈: 플랫 키 구조
        systemd.user.services.custom-notify-logger = {
          description = "Notification Logger Service";
          wantedBy = ["graphical-session.target"];
          after = ["graphical-session-pre.target"];
          partOf = ["graphical-session.target"];
          serviceConfig = {
            ExecStart = "${logger-script}";
            Restart = "always";
            RestartSec = 3;
            Environment = ["LOG_DIR=${svcCfg.logDir}"];
          };
        };
      })
    ];
    hm = lib.mkMerge [
      # cfg.enable → svcCfg.enable 캐스케이드 (HM 컨텍스트)
      {services.custom-notify-logger.enable = lib.mkDefault true;}

      (lib.mkIf svcCfg.enable {
        # == Home Manager: 사용자 서비스 등록 (섹션별 중첩 키 구조) ==
        systemd.user.services.custom-notify-logger = {
          Unit = {
            Description = "Notification Logger Service";
            After = ["graphical-session-pre.target"];
            PartOf = ["graphical-session.target"];
          };
          Install = {
            WantedBy = ["graphical-session.target"];
          };
          Service = {
            ExecStart = "${logger-script}";
            Restart = "always";
            RestartSec = 3;
            Environment = ["LOG_DIR=${svcCfg.logDir}"];
          };
        };
      })
    ];
  });
in {
  inherit (base) imports;

  # services.custom-notify-logger 옵션은 mods.* 경로 밖에 있어 mkModHere options 블록 사용 불가
  options.services.custom-notify-logger = {
    enable = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "Enable the Notification Logger background service.";
    };
    logDir = lib.mkOption {
      type = lib.types.str;
      default = "/var/log/custom-notify-logger";
      description = "Directory path where notification log files are stored.";
    };
  };
}
