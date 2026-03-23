{ pkgs, unstable, lib, metaConfig, ... }: {
  imports = [ ../../lib/hyprland.home.nix ];

  home.packages = with pkgs; [
    bitwarden-desktop
    bitwarden-cli

    unstable.slack

    zed-editor

    unstable.antigravity
    unstable.claude-code
    unstable.gemini-cli

    jdk21 # Antigravity 요구사항

    nodejs_24
    pnpm

    (python312.withPackages (ps: with ps; [ pip virtualenv ]))

    (mkNixLDWrapper fvm [
      stdenv.cc.cc zlib fuse3 icu nss openssl curl expat # 필수 기본 라이브러리
      unzip # fvm 내 flutter install/set 시 압축 해제에 필요

      libGL glib gtk3 cairo pango atk gdk-pixbuf harfbuzz fontconfig freetype # Flutter GUI / 그래픽 관련

      wayland # X11 / Wayland 관련 (JetBrains와 Hyprland 환경 대응)
      # libX11 libXcomposite libXcursor libXdamage libXext libXfixes libXi libXrender libXtst libXrandr libXScrnSaver libxcb libxkbcommon

      alsa-lib libpulseaudio dbus libdrm mesa libnotify # 오디오 및 기타 미디어
    ])
  ] ++ (let
    # IDE 바이너리를 감싸서 옵션을 주입하는 헬퍼 함수
    wrapIDE = pkg: binName: (pkgs.symlinkJoin {
      name = "${pkg.name}-wrapped";
      paths = [ pkg ];
      nativeBuildInputs = [ pkgs.makeWrapper ];
      postBuild = ''
        wrapProgram $out/bin/${binName} \
          --add-flags "-Dsun.java2d.uiScale=1.0"
      '';
    });
  in with unstable; [
    # JetBrains 시리즈
    (wrapIDE unstable.jetbrains.idea "idea")
    (wrapIDE unstable.jetbrains.datagrip "datagrip")
    (wrapIDE unstable.jetbrains.pycharm "pycharm")
    (wrapIDE unstable.jetbrains.webstorm "webstorm")
    (wrapIDE unstable.android-studio "android-studio")
  ]);

  home.sessionVariables = {
    # pnpm: Btrfs CoW(reflink) 사용 강제
    PNPM_PACKAGE_IMPORT_METHOD = "clone";

    # pnpm: 저장소 위치 지정
    PNPM_STORE_DIR = "/home/${metaConfig.username}/.local/share/pnpm/store";
  };

  home.shellAliases = {
    npm = "pnpm";
    npx = "pnpm dlx";
  };

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
