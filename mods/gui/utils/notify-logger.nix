{
  mkModOf,
  lib,
  ...
}: let
  base = mkModOf "mods.gui" __curPos "Custom Notification Logger" ({
    cfg,
    config,
    pkgs,
    lib,
    ...
  }: let
    svcCfg = config.services.custom-notify-logger;

    # 기록·조회·통계·장애 감시 본체는 mods/_tools/desktop/notification-center/notif.py (시험: mods/_tools/desktop/notification-center/tests). 화면(notif ui)은 Textual 이 필요
    py = pkgs.python3.withPackages (ps: [ps.textual]);
    notifDir = pkgs.runCommand "notif-py" {} ''
      mkdir -p $out
      cp ${../../_tools/desktop/notification-center/notif.py} $out/notif.py
      cp ${../../_tools/desktop/notification-center/notif_ui.py} $out/notif_ui.py
      cp ${../../_tools/_lib/_uikit/uikit.py} $out/uikit.py
      cp ${../../_tools/desktop/notification-center/devwatch.py} $out/devwatch.py
    '';
    # busctl/systemctl/journalctl(systemd), pkill(procps), wl-copy, notify-send 를 PATH 에 넣어 서비스 환경에서도 동작하게 함
    notif = pkgs.writeShellScriptBin "notif" ''
      export PATH=${lib.makeBinPath [pkgs.systemd pkgs.procps pkgs.wl-clipboard pkgs.libnotify pkgs.pipewire]}:$PATH
      export NOTIF_LOG_DIR=${svcCfg.logDir}
      exec ${py}/bin/python3 ${notifDir}/notif.py "$@"
    '';
    # 전용 창(class=notif)으로 열기 — 이미 떠 있으면 그 창으로 포커스. 인자: all|apps|problems|stats
    notifOpen = pkgs.writeShellScriptBin "notif-open" ''
      if hyprctl clients -j | ${pkgs.jq}/bin/jq -e '.[] | select(.class == "notif")' >/dev/null 2>&1; then
        exec hyprctl dispatch 'hl.dsp.focus({ window = "class:^notif$" })'
      fi
      exec ${pkgs.uwsm}/bin/uwsm app -- ${pkgs.kitty}/bin/kitty --class notif --title "알림 센터" ${notif}/bin/notif ui "''${1:-all}"
    '';
  in {
    os = lib.mkMerge [
      # cfg.enable → svcCfg.enable 캐스케이드 (NixOS 컨텍스트)
      (lib.mkIf cfg.enable {services.custom-notify-logger.enable = lib.mkDefault true;})

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
            ExecStart = "${notif}/bin/notif record";
            Restart = "always";
            RestartSec = 3;
            Environment = ["LOG_DIR=${svcCfg.logDir}"];
          };
        };
      })
    ];
    hm = lib.mkMerge [
      # cfg.enable → svcCfg.enable 캐스케이드 (HM 컨텍스트)
      (lib.mkIf cfg.enable {services.custom-notify-logger.enable = lib.mkDefault true;})

      (lib.mkIf svcCfg.enable {
        # == Home Manager: 사용자 서비스 등록 (섹션별 중첩 키 구조) ==
        home.packages = [notif notifOpen];

        # 실패한 서비스(시스템+사용자)를 1분마다 확인해 새 실패만 알림(앱 이름 system-health, 긴급)으로 알리고 waybar 의 경고 표시를 갱신
        systemd.user.services.notif-health = {
          Unit.Description = "Failed service watcher (notif health)";
          Service = {
            Type = "oneshot";
            ExecStart = "${notif}/bin/notif health";
          };
        };
        systemd.user.timers.notif-health = {
          Unit.Description = "Failed service watcher timer";
          Timer = {
            OnBootSec = "45s";
            OnUnitActiveSec = "60s";
            AccuracySec = "5s";
          };
          Install.WantedBy = ["timers.target"];
        };

        # 장치 감시: 외부 오디오(USB/블루투스)·헤드폰 연결/해제, USB, 마운트/언마운트, 전원 어댑터 전환을 알림(앱 이름 devices)으로.
        # pasystray 의 자체 알림은 끈다(아래 autostart) — 설정을 다시 읽을 때마다 내장 카드를 "새 장치"로 반복해서 알렸음
        systemd.user.services.notif-devices = {
          Unit = {
            Description = "Device event notifications (notif devices)";
            After = ["graphical-session-pre.target"];
            PartOf = ["graphical-session.target"];
          };
          Install.WantedBy = ["graphical-session.target"];
          Service = {
            ExecStart = "${notif}/bin/notif devices";
            Restart = "always";
            RestartSec = 3;
          };
        };
        # 패키지가 제공하는 XDG 자동 시작 항목을 같은 이름으로 덮어써서 알림만 끔(트레이 아이콘/음량 조작은 그대로)
        xdg.configFile."autostart/pasystray.desktop".text = ''
          [Desktop Entry]
          Type=Application
          Name=PulseAudio System Tray
          Exec=pasystray --notify=none
          NoDisplay=true
        '';

        # 앱 런처(SUPER+Space)에서 "Notification Center" 로 연다 — 전용 단축키는 두지 않음
        xdg.desktopEntries.notif = {
          name = "Notification Center";
          genericName = "Notification history";
          comment = "Search, group, count and copy past notifications; see system problems";
          exec = "${notifOpen}/bin/notif-open";
          terminal = false;
          categories = ["Utility"];
          icon = "preferences-system-notifications";
        };
        wayland.windowManager.hyprland.extraConfig = ''
          hl.window_rule({
            match = { class = "^(notif)$" },
            center = true,
            size = { "monitor_w * 0.7", "monitor_h * 0.75" }
          })
        '';

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
            ExecStart = "${notif}/bin/notif record";
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

  # services.custom-notify-logger 옵션은 mods.* 경로 밖에 있어 mkMod options 블록 사용 불가
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
