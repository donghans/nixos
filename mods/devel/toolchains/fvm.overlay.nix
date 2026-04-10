# FVM (Flutter Version Management) Overlay
_final: prev: let
  # (목적: FVM 바이너리에 동적 링킹 필수 라이브러리 주입)
  wrapFVM = pkg: binName: (prev.mkWrapper {
    inherit pkg binName;
    libs = with prev; [
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
    bins = with prev; [unzip openssl curl libnotify dbus glib xdg-utils];
    env = {
      SHELL = "/run/current-system/sw/bin/sh"; # (이유: FVM이 ~/.bash_profile 읽는 것을 방지)
    };
  });
in {
  fvm-wrapped = wrapFVM prev.fvm "fvm";
}
