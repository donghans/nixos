# HOP — HWP/HWPX 열기·편집 데스크톱 앱 (rhwp 엔진 기반 Tauri 앱, MIT). https://github.com/golbin/hop
# nixpkgs 에 없어서 공식 릴리스 .deb 를 autoPatchelfHook 으로 재포장한다(.deb 안은 hop-desktop 바이너리 + 폰트 + .desktop + 아이콘).
# AppImage 는 fcitx5 한글 입력이 불안정하다고 안내돼 있어 .deb 를 쓴다.
# 버전을 올릴 때: version 을 바꾸고 hash 를 `nix hash file --sri HOP-linux-x64.deb` 값으로 교체.
{mkModOf, ...}:
mkModOf "mods.gui" __curPos "HOP (HWP/HWPX 편집기)" ({pkgs, ...}: let
  hop = pkgs.stdenv.mkDerivation rec {
    pname = "hop";
    version = "0.4.5";
    src = pkgs.fetchurl {
      url = "https://github.com/golbin/hop/releases/download/v${version}/HOP-linux-x64.deb";
      hash = "sha256-S5OmXMevtRvSg/1/b9DMe2udsr5sulNbLuOkW4bCMyo=";
    };
    nativeBuildInputs = with pkgs; [dpkg autoPatchelfHook wrapGAppsHook3];
    buildInputs = with pkgs; [
      gtk3
      glib
      cairo
      gdk-pixbuf
      webkitgtk_4_1
      libsoup_3
      glib-networking # WebKit 의 TLS/네트워크 백엔드
      stdenv.cc.cc.lib
    ];
    unpackPhase = "dpkg-deb -x $src .";
    dontConfigure = true;
    dontBuild = true;
    installPhase = ''
      mkdir -p $out
      cp -r usr/* $out/
      substituteInPlace $out/share/applications/HOP.desktop --replace-fail "Exec=hop-desktop" "Exec=$out/bin/hop-desktop"
    '';
    meta = {
      description = "HWP/HWPX desktop editor built on rhwp";
      homepage = "https://github.com/golbin/hop";
      license = pkgs.lib.licenses.mit;
      mainProgram = "hop-desktop";
      platforms = ["x86_64-linux"];
    };
  };
in {
  hm = {
    home.packages = [hop];
    # .desktop 의 MimeType 은 application/x-hwp, application/vnd.hancom.hwpx. 기본 앱으로 지정(mimeapps.list 는 home-manager 소유).
    xdg.mimeApps.defaultApplications = {
      "application/x-hwp" = ["HOP.desktop"];
      "application/vnd.hancom.hwpx" = ["HOP.desktop"];
    };
  };
})
