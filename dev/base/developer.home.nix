{ pkgs, inputs, unstable, lib, metaConfig, ... }: {
  imports = [ ../../lib/hyprland.home.nix ];

  home.packages = with pkgs; [
    bitwarden-desktop
    bitwarden-cli

    slack

    zed-editor

    unstable.antigravity
    unstable.claude-code
    unstable.gemini-cli

    jdk21 # Antigravity 요구사항

    (python312.withPackages (ps: with ps; [ pip virtualenv ]))

    (pkgs.symlinkJoin {
      name = "fvm-wrapped";
      paths = [(mkNixLDWrapper fvm [
        stdenv.cc.cc zlib fuse3 icu nss openssl curl expat # 필수 기본 라이브러리

        libGL glib gtk3 cairo pango atk gdk-pixbuf harfbuzz fontconfig freetype # Flutter GUI / 그래픽 관련

        wayland # X11 / Wayland 관련 (JetBrains와 Hyprland 환경 대응)
        # libX11 libXcomposite libXcursor libXdamage libXext libXfixes libXi libXrender libXtst libXrandr libXScrnSaver libxcb libxkbcommon

        alsa-lib libpulseaudio dbus libdrm mesa libnotify # 오디오 및 기타 미디어
      ])];
      nativeBuildInputs = [ pkgs.makeWrapper ];
      postBuild = ''
        wrapProgram $out/bin/fvm \
        --prefix PATH : "${pkgs.lib.makeBinPath [ unzip ]}" \
        --set SHELL "/run/current-system/sw/bin/sh"
      '';
    })
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
    (wrapIDE jetbrains.idea "idea")
    (wrapIDE jetbrains.datagrip "datagrip")
    (wrapIDE jetbrains.pycharm "pycharm")
    (wrapIDE jetbrains.webstorm "webstorm")
    (wrapIDE android-studio "android-studio")
  ]) ++ (let
    pkgs-2405 = inputs.nixpkgs-2405.legacyPackages.${pkgs.system};
    # Node를 감싸서 옵션을 주입하는 헬퍼 함수
    wrapNode = pkg: binName: (pkgs.symlinkJoin {
      name = "${pkg.name}-wrapped";
      paths = [(mkNixLDWrapper pkg [
        pkgs-2405.nodePackages.prisma pkgs-2405.prisma-engines stdenv.cc.cc openssl
      ])];
      nativeBuildInputs = [ pkgs.makeWrapper ];
      postBuild = ''
        wrapProgram $out/bin/${binName} \
        --prefix PATH : "${pkgs.lib.makeBinPath [ openssl ]}" \
        --set PNPM_PACKAGE_IMPORT_METHOD "clone" \
        --set PNPM_STORE_DIR "/home/${metaConfig.username}/.local/share/pnpm/store" \
        --set PRISMA_QUERY_ENGINE_LIBRARY "${pkgs-2405.prisma-engines}/lib/libquery_engine.node" \
        --set PRISMA_QUERY_ENGINE_BINARY "${pkgs-2405.prisma-engines}/bin/query-engine" \
        --set PRISMA_SCHEMA_ENGINE_BINARY "${pkgs-2405.prisma-engines}/bin/schema-engine" \
        --set PRISMA_ENGINES_CHECKSUM_IGNORE_MISSING "1" \
        --set PRISMA_CLI_QUERY_ENGINE_TYPE "library"
      '';
    });
  in with pkgs; [
    (wrapNode nodejs_24 "node")
    (wrapNode pnpm "pnpm")
  ]);

  home.shellAliases = {
    npm = "pnpm";
    npx = "pnpm dlx";
    yarn = "pnpm";
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
