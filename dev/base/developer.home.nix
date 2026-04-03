{ pkgs, inputs, unstable, unstable-fallback, lib, metaConfig, ... }: {
  imports = [
    ../../lib/hyprland.home.nix
    ./shell-yarn.nix
  ];

  home.packages = with pkgs; [
    bitwarden-desktop
    bitwarden-cli

    unstable.slack

    unstable.zed-editor

    unstable-fallback.claude-code
    unstable.gemini-cli

    (python312.withPackages (ps: with ps; [ pip virtualenv ]))
  ] ++ (let  # ============== Jetbrains IDEs ===============
    # IDE 바이너리를 감싸서 옵션을 주입하는 헬퍼 함수
    wrapIDE = pkg: binName: (pkgs.mkWrapper {
      inherit pkg binName;
      addFlags = [ "-Dsun.java2d.uiScale=1.0" ];
    });
  in with unstable; [
    # JetBrains 시리즈
    (wrapIDE jetbrains.idea "idea")
    (wrapIDE jetbrains.datagrip "datagrip")
    (wrapIDE jetbrains.pycharm "pycharm")
    (wrapIDE jetbrains.webstorm "webstorm")
    (wrapIDE android-studio "android-studio")
  ]) ++ (let # ==================== FVM ====================
    # FVM 바이너리를 감싸서 옵션 및 라이브러리를 주입하는 헬퍼 함수
    wrapFVM = pkg: binName: (pkgs.mkWrapper {
      inherit pkg binName;
      libs = [
        stdenv.cc.cc zlib fuse3 icu nss openssl curl expat # 필수 기본 라이브러리

        libGL glib gtk3 cairo pango atk gdk-pixbuf harfbuzz fontconfig freetype # Flutter GUI / 그래픽 관련

        wayland # X11 / Wayland 관련 (JetBrains와 Hyprland 환경 대응)
        # libX11 libXcomposite libXcursor libXdamage libXext libXfixes libXi libXrender libXtst libXrandr libXScrnSaver libxcb libxkbcommon

        alsa-lib libpulseaudio dbus libdrm mesa libnotify # 오디오 및 기타 미디어
      ];
      bins = [ unzip openssl curl libnotify dbus glib xdg-utils ];
      env = { SHELL = "/run/current-system/sw/bin/sh"; }; # FVM이 ~/.bash_profile 읽는것을 방지
    });
  in with pkgs; [
    (wrapFVM fvm "fvm")
  ]) ++ (let # ========== Node.js / pnpm / Prisma ==========
    # Prisma 엔진을 현재 디렉토리에서 상위로 올라가며 찾는 쉘 스크립트
    prisma_detection_script = ''
      curr="$PWD"
      while [ "$curr" != "/" ]; do
        if [ -d "$curr/node_modules/@prisma/engines" ]; then
          export PRISMA_ENGINES_DIR="$curr/node_modules/@prisma/engines"
          # 플랫폼Suffix(linux-musl 등)가 붙은 엔진 바이너리들을 자동으로 찾습니다.
          export PRISMA_QUERY_ENGINE_LIBRARY=$(find "$PRISMA_ENGINES_DIR" -name "libquery_engine-*" | head -n 1)
          export PRISMA_QUERY_ENGINE_BINARY=$(find "$PRISMA_ENGINES_DIR" -name "query-engine-*" | head -n 1)
          export PRISMA_SCHEMA_ENGINE_BINARY=$(find "$PRISMA_ENGINES_DIR" -name "schema-engine-*" | head -n 1)
          break
        fi
        curr=$(dirname "$curr")
      done
    '';

    # Node를 감싸서 옵션 및 라이브러리를 주입하는 헬퍼 함수
    wrapNode = pkg: binName: (pkgs.mkWrapper {
      inherit pkg binName;
      libs = [ stdenv.cc.cc openssl ];
      bins = [ openssl findutils ];
      addFlags = [ "--run '${prisma_detection_script}'" ];
      env = {
        PNPM_PACKAGE_IMPORT_METHOD = "reflink"; # Btrfs CoW를 활용한 용량 및 성능 최적화
        PNPM_PUBLIC_HOIST_PATTERN = "*"; # Yarn v1/npm 스타일의 호이스팅 모방 (호환성 극대화)
        PNPM_SHAMEFULLY_HOIST = "true"; # 의존성 내의 의존성까지 모두 호이스팅
        PNPM_STORE_DIR = "/home/${metaConfig.username}/.local/share/pnpm/store";
      };
    });

  in with pkgs; [
    (wrapNode nodejs_24 "node")
    (wrapNode pnpm "pnpm")
  ]);

  home.shellAliases = {
    npm = "pnpm";
    npx = "pnpm dlx";
  };

  programs.git.enable = true;
  programs.git.settings.user.name  = metaConfig.gitName;
  programs.git.settings.user.email = metaConfig.gitEmail;

  xdg.mimeApps.defaultApplications = {
    "x-scheme-handler/slack" = [ "slack.desktop" ];
  };

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
