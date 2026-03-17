{ pkgs, unstable, lib, metaConfig, ... }: {
  imports = [ ../../lib/hyprland.home.nix ];

  home.username = metaConfig.username;
  home.homeDirectory = "/home/${metaConfig.username}";

  home.packages = with pkgs; [
    bitwarden-desktop
    bitwarden-cli

    unstable.slack

    unstable.jetbrains.idea
    unstable.jetbrains.webstorm
    unstable.android-studio
    zed-editor

    unstable.antigravity

    jdk21 # Antigravity 요구사항

    nodejs_24
    pnpm

    (python312.withPackages (ps: with ps; [ pip virtualenv ]))

    (mkNixLDWrapper fvm [
      # 필수 기본 라이브러리
      stdenv.cc.cc zlib fuse3 icu nss openssl curl expat

      # Flutter GUI / 그래픽 관련
      libGL glib gtk3 cairo pango atk gdk-pixbuf harfbuzz fontconfig freetype

      # X11 / Wayland 관련 (JetBrains와 Hyprland 환경 대응)
      # libX11 libXcomposite libXcursor libXdamage libXext libXfixes libXi libXrender libXtst libXrandr libXScrnSaver libxcb libxkbcommon
      wayland

      # 오디오 및 기타 미디어
      alsa-lib libpulseaudio dbus libdrm mesa libnotify
    ])

    unzip # fvm 내 flutter 압축 해제에 필요
  ];

  # pnpm 전역 설정을 파일로 직접 관리
  home.file.".nmprc".text = ''
    package-import-method=clone
    store-dir=${config.home.homeDirectory}/.local/share/pnpm/store
  '';

  programs.git.enable = true;
  programs.git.settings.user.name  = metaConfig.gitName;
  programs.git.settings.user.email = metaConfig.gitEmail;

  wayland.windowManager.hyprland.settings = {
    input = {
      # 1. 마우스 기본 속도 (-1.0 ~ 1.0, 0이 기본값)
      sensitivity = lib.mkForce 1;

      # 2. 마우스 가속 프로필
      # "flat"으로 설정하면 가속이 꺼지고 일정한 속도로 움직입니다 (개발자분들이 선호함)
      # "adaptive"가 기본 가속 모드입니다.
      accel_profile = "adaptive";
    };
  };
}
