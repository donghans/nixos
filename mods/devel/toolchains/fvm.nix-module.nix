# [working-refactor] 해당 구문은 before-refactor/lib/developer.home/fvm.nix 에 있었음
# [working-refactor] 해당 구문은 after-refactor/... 로 들어가야 함
{pkgs, ...}: let
  # (목적: FVM 바이너리에 동적 링킹 필수 라이브러리 주입)
  wrapFVM = pkg: binName: (pkgs.mkWrapper {
    inherit pkg binName;
    libs = with pkgs; [
      stdenv.cc.cc
      zlib
      fuse3
      icu
      nss
      openssl
      curl
      expat
      libGL
      glib
      gtk3
      cairo
      pango
      atk
      gdk-pixbuf
      harfbuzz
      fontconfig
      freetype
      wayland
      alsa-lib
      libpulseaudio
      dbus
      libdrm
      mesa
      libnotify
    ];
    bins = with pkgs; [unzip openssl curl libnotify dbus glib xdg-utils];
    env = {
      SHELL = "/run/current-system/sw/bin/sh"; # (이유: FVM이 ~/.bash_profile 읽는 것을 방지)
      FVM_HOME = "$HOME/.fvm"; # (목적: HOME 디렉터리 정리를 위해 숨김 폴더 사용)
    };
  });
in {
  home.packages = [
    (wrapFVM pkgs.fvm "fvm")
  ];

  # 터미널 환경에서도 FVM_HOME을 인식하도록 설정
  home.sessionVariables = {
    FVM_HOME = "$HOME/.fvm";
  };
}
