{ pkgs, config, notifyLog, ... }: let
  notifyLogger = pkgs.writeShellScriptBin "notify-logger" ''
    mkdir -p $(dirname "${notifyLog}")

    # dbus-monitor의 출력을 한 줄씩 읽으면서 상태 관리
    ${pkgs.dbus}/bin/dbus-monitor "interface='org.freedesktop.Notifications',member='Notify'" | \
    while read -r line; do
      # 새로운 알림 메시지가 시작됨을 감지
      if echo "$line" | grep -q "member=Notify"; then
        count=0
        summary=""
        body=""
      fi

      # 'string "' 문구가 포함된 라인에서 내용 추출
      if echo "$line" | grep -q 'string "'; then
        count=$((count + 1))
        # sed로 큰따옴표 안의 내용만 추출
        content=$(echo "$line" | sed 's/.*string "\(.*\)".*/\1/')

        # 1: app_name, 2: icon, 3: summary, 4: body
        # (replaces_id가 중간에 uint32로 끼어있어 string 기준으로는 순서가 당겨짐)
        if [ $count -eq 3 ]; then
          summary="$content"
        elif [ $count -eq 4 ]; then
          body="$content"

          # Summary와 Body가 모두 확보된 시점에 한 줄로 기록
          if [ -n "$summary" ]; then
            echo "[$(date +'%Y-%m-%d %H:%M:%S')] [$summary] $body" >> "${notifyLog}"
            # 중복 기록 방지를 위해 count 초기화
            count=99
          fi
        fi
      fi
    done
  '';

  # logrotate용 전용 설정 파일 내용
  logrotateConf = pkgs.writeText "notify-logrotate.conf" ''
    "${notifyLog}" {
      daily
      rotate 30
      delaycompress
      missingok
      notifempty
      # 유저 권한이므로 'create'에 사용자명을 명시하지 않아도 됩니다.
      create 0644
    }
  '';

  cliphist = "${pkgs.cliphist}/bin/cliphist";
  wl-paste = "${pkgs.wl-clipboard}/bin/wl-paste";
in {
  wayland.windowManager.hyprland.systemd = {
    enable = true;
    variables = ["--all"];
  };

  wayland.windowManager.hyprland.settings = {
    "exec-once" = [
      # 1. 시스템 설정 관련 (uwsm 없이 직접 실행해도 무방한 것들)
      "hyprctl setcursor Bibata-Modern-Ice 24"

      # 2. 필수 서비스 (uwsm app 사용)
      "uwsm app -- fcitx5"
      "uwsm app -- ${pkgs.hyprpolkitagent}/libexec/hyprpolkitagent"
      "uwsm app -- ${pkgs.networkmanagerapplet}/bin/nm-applet"

      # 3. UI 및 배경화면 (분리 실행 권장)
      "uwsm app -- ${pkgs.waybar}/bin/waybar"
      "uwsm app -- ${pkgs.hyprpaper}/bin/hyprpaper"

      # 4. 클립보드 매니저
      "uwsm app -- ${wl-paste} --type text --watch ${cliphist} store"
      "uwsm app -- ${wl-paste} --type image --watch ${cliphist} store"

      # 5. 알림 및 로그
      "uwsm app -- ${notifyLogger}/bin/notify-logger"
    ];
  };

  home.sessionVariables = {
    # 커서 설정
    XCURSOR_SIZE = "24";
    HYPRCURSOR_SIZE = "24";

    # 입력기 (Fcitx5)
    GTK_IM_MODULE = ""; # GTK4부터는 비워두는 것이 권장됩니다.
    QT_IM_MODULE = "fcitx";
    XMODIFIERS = "@im=fcitx";
    SDL_IM_MODULE = "fcitx";
    INPUT_METHOD = "fcitx";

    # 테마 및 플랫폼
    GTK_THEME = "Adwaita-dark";
    QT_QPA_PLATFORM = "wayland;xcb"; # xcb fallback 추가 권장

    # 데스크탑 환경 식별
    XDG_CURRENT_DESKTOP = "Hyprland";
    XDG_SESSION_TYPE = "wayland";
    XDG_SESSION_DESKTOP = "Hyprland";

    # 비밀번호 저장소를 gnome-keyring으로 강제 지정
    # (Vivaldi 실행 인자에 --password-store=gnome-libsecret 를 주는 것과 같은 효과)
    PYTHON_EGG_CACHE = "$XDG_CACHE_HOME/python-eggs"; # 예시일 뿐, 아래가 중요합니다.

    # 크로미움 계열 키링 연동을 위한 설정
    CHROME_EXECUTABLE = "vivaldi";
    BROWSER = "vivaldi";

    # 기타 앱 힌트
    ELECTRON_OZONE_PLATFORM_HINT = "auto";
    _JAVA_AWT_WM_NONREPARENTING = "1";
  };

  # 유저 레벨 logrotate 실행 서비스
  systemd.user.services.notify-logrotate = {
    Unit = { Description = "Rotate notification logs"; };
    Service = {
      # --state 옵션을 사용해 유저 디렉토리에 상태 파일을 저장하는게 핵심입니다.
      ExecStart = "${pkgs.logrotate}/bin/logrotate --state ${config.home.homeDirectory}/.local/share/logrotate.state ${logrotateConf}";
    };
  };

  # 매일 실행되게 만드는 타이머
  systemd.user.timers.notify-logrotate = {
    Unit = { Description = "Daily rotation of notification logs"; };
    Timer = {
      OnCalendar = "daily";
      Persistent = true; # 컴퓨터가 꺼져있어서 놓쳤다면 켰을 때 즉시 실행
    };
    Install = { WantedBy = [ "timers.target" ]; };
  };
}
