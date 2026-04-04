{
  pkgs,
  unstable,
  unstable-fallback,
  lib,
  metaConfig,
  ...
}: {
  imports = [
    ../../lib/hyprland.home.nix
    ./shell-yarn.nix
  ];

  home.packages = with pkgs;
    [
      bitwarden-desktop
      bitwarden-cli

      unstable.slack

      unstable.zed-editor

      unstable-fallback.claude-code
      unstable.gemini-cli

      (python312.withPackages (ps: with ps; [pip virtualenv]))
    ]
    ++ (let
      # == Jetbrains IDEs ==
      # (목적: UI 스케일 고정 등 환경 변수 주입 래퍼)
      wrapIDE = pkg: binName: (pkgs.mkWrapper {
        inherit pkg binName;
        addFlags = ["-Dsun.java2d.uiScale=1.0"];
      });
    in
      with unstable; [
        # JetBrains 시리즈
        (wrapIDE jetbrains.idea "idea")
        (wrapIDE jetbrains.datagrip "datagrip")
        (wrapIDE jetbrains.pycharm "pycharm")
        (wrapIDE jetbrains.webstorm "webstorm")
        (wrapIDE android-studio "android-studio")
      ])
    ++ (let
      # == FVM & Flutter ==
      # (목적: FVM 바이너리에 동적 링킹 필수 라이브러리 주입)
      wrapFVM = pkg: binName: (pkgs.mkWrapper {
        inherit pkg binName;
        libs = [
          stdenv.cc.cc
          zlib
          fuse3
          icu
          nss
          openssl
          curl
          expat # 필수 기본 라이브러리

          libGL
          glib
          gtk3
          cairo
          pango
          atk
          gdk-pixbuf
          harfbuzz
          fontconfig
          freetype # Flutter GUI / 그래픽 관련

          wayland
          # [OPTIONAL] X11 fallback libraries
          # libX11 libXcomposite libXcursor libXdamage libXext libXfixes libXi libXrender libXtst libXrandr libXScrnSaver libxcb libxkbcommon

          alsa-lib
          libpulseaudio
          dbus
          libdrm
          mesa
          libnotify
        ];
        bins = [unzip openssl curl libnotify dbus glib xdg-utils];
        env = {SHELL = "/run/current-system/sw/bin/sh";}; # (이유: FVM이 ~/.bash_profile 읽는 것을 방지)
      });
    in
      with pkgs; [
        (wrapFVM fvm "fvm")
      ])
    ++ (let
      # == Node.js / pnpm / Prisma ==
      # (목적: Prisma 엔진 로컬 탐색 쉘 스크립트)
      prismaDetectionScript = ''
        curr="''$PWD"
        while [ "''$curr" != "/" ]; do
          if [ -d "''$curr/node_modules/@prisma/engines" ]; then
            export PRISMA_ENGINES_DIR="''$curr/node_modules/@prisma/engines"
            # 플랫폼Suffix(linux-musl 등)가 붙은 엔진 바이너리들을 자동으로 찾습니다.
            export PRISMA_QUERY_ENGINE_LIBRARY=$(find "''$PRISMA_ENGINES_DIR" -name "libquery_engine-*" | head -n 1)
            export PRISMA_QUERY_ENGINE_BINARY=$(find "''$PRISMA_ENGINES_DIR" -name "query-engine-*" | head -n 1)
            export PRISMA_SCHEMA_ENGINE_BINARY=$(find "''$PRISMA_ENGINES_DIR" -name "schema-engine-*" | head -n 1)
            break
          fi
          curr=$(dirname "''$curr")
        done
      '';

      # (목적: Node 환경에 Prisma 탐색 및 PNPM 글로벌 최적화 변수 주입)
      wrapNode = pkg: binName: (pkgs.mkWrapper {
        inherit pkg binName;
        libs = [stdenv.cc.cc openssl];
        bins = [openssl findutils];
        run = prismaDetectionScript;
        env = {
          PNPM_PACKAGE_IMPORT_METHOD = "reflink"; # (이유: Btrfs CoW 활용 성능 최적화)
          PNPM_PUBLIC_HOIST_PATTERN = "*";
          PNPM_SHAMEFULLY_HOIST = "true"; # (이유: 패키지 호이스팅 호환성 극대화)
          PNPM_STORE_DIR = "/home/${metaConfig.username}/.local/share/pnpm/store";
        };
      });
    in
      with pkgs; [
        (wrapNode nodejs_24 "node")
        (wrapNode pnpm "pnpm")
      ]);

  home.shellAliases = {
    npm = "pnpm";
    npx = "pnpm dlx";
  };

  programs.git.enable = true;
  programs.git.settings = {
    user.name = metaConfig.gitName;
    user.email = metaConfig.gitEmail;
    url."git@github.com:".insteadOf = "https://github.com/";
  };

  xdg.mimeApps.defaultApplications = {
    "x-scheme-handler/slack" = ["slack.desktop"];
  };

  wayland.windowManager.hyprland.settings = {
    input = {
      sensitivity = lib.mkForce 1;
      # (목적: 개발자용 flat 프로필 대신 기본 adaptive 가속 유지)
      accel_profile = "adaptive";
    };
  };
}
