# Thunar (XFCE 파일 관리자) — 기본 파일 관리자.
# - 폴더 기본 연결(inode/directory)을 Thunar 로 지정 (지정 전에는 kitty-open.desktop 이 열렸음)
# - thunar-archive-plugin: 우클릭 "Extract Here / Extract To… / Create Archive…". 플러그인은 압축 파일의 기본 앱
#   desktop-id 이름의 `<id>.tap` 을 자기 libexec 에서 찾는데(xarchiver.desktop → xarchiver.tap),
#   Xarchiver 의 .tap 은 Xarchiver 패키지 쪽에 있으므로 플러그인 libexec 에 심볼릭 링크로 연결한다.
# - thunar-volman: USB 등 이동식 장치 자동 마운트 (gvfs·udisks2 는 mods/sys/vfs.nix). udiskie 는 쓰지 않음
#   (Nemo 에서 언마운트할 일이 많은데 udiskie 와 겹쳐 쓸 이유가 없어 대체). thunar-volman 은 데몬이 아니라
#   Thunar 데몬(`thunar --daemon`)이 장치 이벤트마다 실행하므로 데몬을 세션 시작 때 띄워야 하고,
#   자동 마운트는 기본이 꺼져 있어 xfconf 로 켠다. (알림/트레이 없음)
# - tumbler: 썸네일 서비스 (영상/이미지/PDF/폰트/ePub 썸네일러 내장)
# 분할 보기(듀얼 패널)는 Thunar 4.20 에 내장 — F3
{mkModOf, ...}:
mkModOf "mods.gui" __curPos "Thunar (기본 파일 관리자)" ({
  pkgs,
  lib,
  ...
}: {
  os = {
    programs.thunar = {
      enable = true; # programs.xfconf(설정 저장용 dbus 서비스)도 함께 켜짐
      plugins = [
        (pkgs.thunar-archive-plugin.overrideAttrs (old: {
          postInstall =
            (old.postInstall or "")
            + ''
              ln -s ${pkgs.xarchiver}/libexec/thunar-archive-plugin/xarchiver.tap \
                $out/libexec/thunar-archive-plugin/xarchiver.tap
            '';
        }))
        pkgs.thunar-volman
      ];
    };

    services.tumbler.enable = true;
  };

  hm = {
    # thunar-volman 이 장치 이벤트를 받으려면 Thunar 데몬이 떠 있어야 함
    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 900 [
      "uwsm app -- thunar --daemon"
    ];

    xfconf.settings.thunar-volman = {
      "automount-drives/enabled" = true;
      "automount-media/enabled" = true;
    };

    xdg.mimeApps.defaultApplications."inode/directory" = "thunar.desktop";

    # Thunar 의 "여기서 터미널 열기" 는 exo 의 선호 터미널을 씀 (기본은 xterm 계열)
    xdg.configFile."xfce4/helpers.rc".text = ''
      TerminalEmulator=kitty
    '';
  };
})
