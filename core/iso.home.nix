{pkgs, lib, ...}: {
  imports = [];

  home.username = "nixos";
  home.homeDirectory = "/home/nixos";

  home.packages = with pkgs; [
    zed-editor
  ];

  # == Hide Default Application Icons ==
  # (목적: 메뉴에서 xterm을 가려서 커스텀 인스톨러 느낌을 강화)
  xdg.desktopEntries = {
    xterm = {
      name = "XTerm (Hidden)";
      noDisplay = true;
    };
  };

  # base/home.nix의 SSH URL 리다이렉트 제거
  # base에서 url."git@github.com:".insteadOf = "https://github.com/" 를 설정하는데,
  # ISO는 SSH 키가 없으므로 https:// clone이 SSH로 리다이렉트되어 실패함
  programs.git.settings = lib.mkForce {
    user.name = "nixos";
    user.email = "nixos@localhost";
  };

  # spice-vdagent (유저 세션 에이전트) 자동 시작
  # spice-vdagentd(system daemon, iso.nix에서 활성화)가 virtio-serial을 담당하고,
  # spice-vdagent(user session)가 클립보드·해상도 등 유저 세션 기능을 담당한다.
  # 유저 세션 에이전트는 자동으로 시작되지 않으므로 Hyprland exec-once로 실행.
  wayland.windowManager.hyprland.settings.exec-once = [
    "${pkgs.spice-vdagent}/bin/spice-vdagent"
  ];

  # Wayland → X11 클립보드 브릿지
  #
  # NixOS nixpkgs의 spice-vdagent는 GTK3 없이 빌드되어 순수 X11 전용이다.
  # Wayland 클립보드를 직접 볼 수 없고 DISPLAY=:0 (XWayland)의 X11 클립보드만 감시한다.
  # Hyprland의 자체 Wayland→X11 동기화가 VM 환경에서 불안정하므로,
  # wl-paste --watch로 Wayland 클립보드 변화를 직접 감지해 X11에 써줌으로써
  # spice-vdagent가 변화를 감지 → SPICE 채널 → 호스트 클립보드로 이어지게 한다.
  #
  # 반대 방향(X11→Wayland)은 wl-clip.nix의 x11-clipboard-bridge가 이미 담당.
  systemd.user.services.wayland-x11-clipboard-bridge = {
    Unit = {
      Description = "Wayland to X11 clipboard bridge for spice-vdagent";
      After = ["graphical-session.target"];
      PartOf = ["graphical-session.target"];
    };
    Service = {
      ExecStart = "${pkgs.wl-clipboard}/bin/wl-paste --type text/plain --watch ${pkgs.xclip}/bin/xclip -selection clipboard -i";
      Restart = "on-failure";
      RestartSec = "2";
    };
    Install.WantedBy = ["graphical-session.target"];
  };

  # (프리셋 mods는 flake.nix의 custom-iso extraModules에서 주입)
}
