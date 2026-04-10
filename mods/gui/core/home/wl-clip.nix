{
  pkgs,
  lib,
  config,
  ...
}:
with lib; let
  # XWayland→Wayland 클립보드 브릿지 스크립트
  #
  # [문제] JetBrains(XWayland) 클립보드를 Wayland 앱이 읽을 때 MIME 협상 단계에서
  #        교착이 발생함. GTK/Electron 앱이 text/html을 우선 요청하면 JVM 응답이 느려
  #        전체 클립보드가 블록되어 ANR 발생. 몇 번 복사를 반복하면 미처리 hang 요청이
  #        쌓여 누적적으로 악화됨.
  #
  # [해결] X11 클립보드 변경을 clipnotify로 이벤트 기반 감지 후, xclip으로 X11끼리
  #        plain text를 읽고 wl-copy로 Wayland 네이티브 클립보드에 재발행.
  #        Wayland 앱들은 XWayland 브릿지 대신 이 네이티브 소스에서 읽어 ANR 없이
  #        붙여넣기 가능. 또한 브릿지가 클립보드 내용을 wl-copy 프로세스에 보존하므로
  #        wl-clip-persist 없이도 JetBrains 종료 후에도 클립보드 유지.
  x11ClipboardBridge = pkgs.writeShellScript "x11-clipboard-bridge" ''
    PREV=""
    while ${pkgs.clipnotify}/bin/clipnotify; do
      CONTENT=$(${pkgs.xclip}/bin/xclip -selection clipboard -o -target UTF8_STRING 2>/dev/null \
             || ${pkgs.xclip}/bin/xclip -selection clipboard -o -target STRING 2>/dev/null \
             || true)
      if [ -n "$CONTENT" ] && [ "$CONTENT" != "$PREV" ]; then
        PREV="$CONTENT"
        printf '%s' "$CONTENT" | ${pkgs.wl-clipboard}/bin/wl-copy
      fi
    done
  '';
in {
  # == 클립보드 관리 ==
  config = mkIf config.mods.gui.enable {
    # wl-clip-persist 제거:
    # - 브릿지(x11-clipboard-bridge)가 이미 XWayland 클립보드를 wl-copy 프로세스에 보존
    # - wl-clip-persist는 소유자 전환 시 복잡한 MIME 타입 읽기를 시도하여
    #   hang 누적의 추가 원인이 될 수 있음

    home.packages = [pkgs.clipnotify pkgs.xclip];

    # 클립보드 히스토리 매니저 (기본 서비스 비활성화 후 커스텀으로 교체)
    # 기본 wl-paste --watch는 "최적" MIME 타입(→ text/html)을 요청해 XWayland에서 블록됨
    services.cliphist.enable = false;

    systemd.user.services.cliphist = {
      Unit = {
        Description = "Clipboard history (text-only, XWayland safe)";
        After = ["graphical-session.target"];
        PartOf = ["graphical-session.target"];
      };
      Service = {
        ExecStart = "${pkgs.wl-clipboard}/bin/wl-paste --type text/plain --watch ${pkgs.cliphist}/bin/cliphist store";
        Restart = "on-failure";
        RestartSec = 2;
      };
      Install.WantedBy = ["graphical-session.target"];
    };

    # X11→Wayland 클립보드 브릿지 데몬
    systemd.user.services.x11-clipboard-bridge = {
      Unit = {
        Description = "X11 to Wayland clipboard bridge (XWayland ANR fix)";
        After = ["graphical-session.target"];
        PartOf = ["graphical-session.target"];
      };
      Service = {
        ExecStart = "${x11ClipboardBridge}";
        Restart = "on-failure";
        RestartSec = 2;
      };
      Install.WantedBy = ["graphical-session.target"];
    };
  };
}
