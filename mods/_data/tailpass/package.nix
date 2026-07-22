/*
  tailpass-app — 이미 빌드된 .deb(`./build.sh app`이 만든
  `target/release/bundle/deb/Tailpass_<version>_amd64.deb`)를 autoPatchelfHook으로
  재포장하는 파생물. nixpkgs의 vscode/discord류와 동일한 패턴 — Tauri/webkit2gtk/tss-esapi
  등 네이티브 의존성을 Nix로 처음부터 재빌드하지 않고, 이미 검증된 Docker 기반 빌드
  파이프라인(build.sh)의 산출물을 그대로 신뢰한다.

  postinst.sh/AppRun.template이 하던 systemd 유닛·D-Bus 정책·polkit daemon-setup
  action·계정 생성은 이 파생물에 포함하지 않는다 — deploy/nix/modules/{daemon,authagent}.nix
  NixOS 모듈이 선언적으로 대체한다. daemon-setup.policy(계정 설치용 pkexec 트리거)는
  NixOS 배포에서 완전히 무의미하므로 설치하지 않는다.

  .deb 안의 실제 파일 배치는 `dpkg-deb -x`로 실측 확인했다(로드맵 B 이후 이 파일 배치는
  clients/app/src-tauri/Cargo.toml의 [package.metadata.packager.deb]/externalBinaries
  설정 + deploy/inject-deb-scripts.sh가 만드는데, 최종 산출물로 어디에 떨어지는지는
  소스만 봐서는 알 수 없어 실제 .deb를 풀어 확인함).
*/
{ lib
, stdenv
, autoPatchelfHook
, makeWrapper
, dpkg
, webkitgtk_4_1
, gtk3
, glib
, cairo
, gdk-pixbuf
, dbus
, libsoup_3
, tpm2-tss
, systemd
, libayatana-appindicator
, wayland
, libxkbcommon
, libGL
, xdg-utils
, desktop-file-utils
, debSrc
}:

stdenv.mkDerivation {
  pname = "tailpass-app";
  # .deb 파일명(Tailpass_<version>_amd64.deb)에서 버전을 뽑아낼 수도 있지만, debSrc가
  # 임의 로컬 경로로 주입되므로(로컬 경로 입력 방식, GitHub Release fetchurl 아님) 파일명
  # 규칙에 의존하지 않는다.
  version = "local";

  src = debSrc;

  nativeBuildInputs = [ autoPatchelfHook makeWrapper dpkg ];

  # ldd 실측 기반 (tailpass-app, tailpass-authagent, tailpass-ceremony의 미해결 의존성).
  # tailpass-daemon/tailpass-daemon-nm/tailpass-cli는 glibc/libgcc뿐이라 추가 buildInputs
  # 불필요 — autoPatchelfHook이 자동으로 처리한다.
  buildInputs = [
    webkitgtk_4_1
    gtk3
    glib
    cairo
    gdk-pixbuf
    dbus
    libsoup_3
    tpm2-tss
    systemd # libudev.so.1 (tailpass-ceremony)
  ];

  # 아래 라이브러리들은 전부 ELF NEEDED가 아니라 런타임 dlopen()으로 찾는다 —
  # ldd/autoPatchelfHook은 NEEDED만 스캔하므로 실기 실행에서야 발견됨:
  #   - libayatana-appindicator3.so.1(트레이 아이콘, Tauri) —
  #     "Failed to load ayatana-appindicator3 ... No such file or directory"
  #   - libwayland-client.so/libxkbcommon.so(winit, tailpass-ceremony) —
  #     "winit EventLoopError: ... The wayland library could not be loaded"로
  #     프로세스 자체가 즉시 죽는다
  #   - libGL.so.1 — egui(tailpass-ceremony)의 glow(OpenGL) 렌더 백엔드도 동일하게
  #     dlopen 기반이라 선제적으로 같이 넣는다
  # buildInputs에 넣어도 autoPatchelfHook이 rpath에 안 넣어주므로(ELF가 이 라이브러리들을
  # NEEDED로 선언하지 않음) makeWrapper로 LD_LIBRARY_PATH를 직접 주입해야 한다.
  #
  # tailpass-app 전용 추가 조치:
  #   - PATH: tauri-plugin-deep-link가 Linux에서 `tailpass://` 스킴 등록에
  #     xdg-mime/update-desktop-database를 Command::new(...)로 셸아웃한다(크레이트
  #     문서에 명시된 요구사항). PATH에 없으면 "deep link register failed: No such
  #     file or directory (os error 2)"로 조용히 실패한다(앱 실행 자체는 안 막음).
  #
  # 한때 WEBKIT_DISABLE_COMPOSITING_MODE/WEBKIT_DISABLE_DMABUF_RENDERER를 스케일
  # 오류의 표준 우회책으로 넣었었으나(WebKitGTK의 DMA-BUF 가속 렌더러가 스케일 팩터를
  # 잘못 계산하는 문제), 실기 확인 결과 진짜 원인은 아래 __EGL_VENDOR_LIBRARY_DIRS
  # 미설정이었다. AppImage(deploy/AppRun.template)는 이 두 변수를 전혀 설정하지
  # 않는데도 정상 배율로 렌더링되므로, 이 패키지만 WebKitGTK을 비가속 경로로 강제
  # 진입시켜 AppImage와 다른 스케일 계산 경로를 타게 만드는 원인일 가능성이 있어
  # 제거했다 — EGL vendor dir 픽스만으로 AppImage와 동일한 가속 경로를 타는지 실기
  # 재검증 필요.
  #
  # AppImage(deploy/AppRun.template)와의 결정적 차이: AppRun은
  # `/run/opengl-driver/share/glvnd/egl_vendor.d`(NixOS가 실제 GPU 드라이버에 맞춰
  # 관리하는 GLVND EGL vendor ICD 심볼릭 링크, hardware.graphics.enable)를
  # __EGL_VENDOR_LIBRARY_DIRS로 명시한다. 이게 없으면 GLVND가 이 패키지에 딸려온
  # nixpkgs 범용 libGL/Mesa의 기본 vendor.d(호스트의 실제 GPU 드라이버와 다를 수
  # 있음)로 폴백해 WebKitGTK의 EGL 컴포지팅 경로가 스케일 팩터를 잘못 계산 —
  # AppImage에서는 정상인데 이 패키지에서만 UI가 축소되어 보인 실제 원인.
  # /run/opengl-driver는 빌드 시점이 아니라 대상 머신에서만 존재 여부를 알 수
  # 있으므로 --set(빌드 시 고정값)이 아니라 --run(실행 시 조건부 export)으로 넣는다.
  postFixup = let
    runtimeLibPath = lib.makeLibraryPath [
      libayatana-appindicator
      wayland
      libxkbcommon
      libGL
    ];
    eglVendorRunSnippet = ''
      if [ -d "/run/opengl-driver/share/glvnd/egl_vendor.d" ]; then
        export __EGL_VENDOR_LIBRARY_DIRS="/run/opengl-driver/share/glvnd/egl_vendor.d:$__EGL_VENDOR_LIBRARY_DIRS"
      fi
    '';
  in ''
    wrapProgram $out/bin/tailpass-app \
      --prefix LD_LIBRARY_PATH : ${runtimeLibPath} \
      --prefix PATH : ${lib.makeBinPath [ xdg-utils desktop-file-utils ]} \
      --run ${lib.escapeShellArg eglVendorRunSnippet}
    wrapProgram $out/bin/tailpass-ceremony \
      --prefix LD_LIBRARY_PATH : ${runtimeLibPath} \
      --run ${lib.escapeShellArg eglVendorRunSnippet}
  '';

  dontBuild = true;
  dontConfigure = true;

  unpackPhase = ''
    runHook preUnpack
    dpkg-deb -x "$src" .
    runHook postUnpack
  '';

  installPhase = ''
    runHook preInstall

    install -Dm755 -t $out/bin \
      usr/bin/tailpass-app \
      usr/bin/tailpass-daemon \
      usr/bin/tailpass-daemon-nm \
      usr/bin/tailpass-cli \
      usr/bin/tailpass-authagent \
      usr/bin/tailpass-ceremony

    # 로드맵 B(cargo-packager 이전) 이후 데스크톱 파일명이 productName(Tailpass)이
    # 아니라 패키지/바이너리명(tailpass-app) 기준으로 바뀌었다 — 실제 .deb를 풀어
    # 확인함(cargo-packager의 DebianConfig.package_name 기본값 규칙).
    install -Dm644 usr/share/applications/tailpass-app.desktop \
      $out/share/applications/tailpass-app.desktop
    install -Dm644 usr/share/icons/hicolor/32x32/apps/tailpass-app.png \
      $out/share/icons/hicolor/32x32/apps/tailpass-app.png

    # 참고용 폰트/fontconfig 사본 — 실제 시스템 등록은 deploy/nix/modules에서
    # fonts.packages/fontconfig conf 옵션으로 처리한다(이 파생물 설치만으로는 자동 적용 안 됨).
    install -Dm644 -t $out/share/fonts/truetype/tailpass \
      usr/share/fonts/truetype/tailpass/NotoSansKR-Regular-latin.ttf \
      usr/share/fonts/truetype/tailpass/NotoSansKR-Regular-korean.ttf
    install -Dm644 etc/fonts/conf.d/70-tailpass-notosanskr.conf \
      $out/share/tailpass/70-tailpass-notosanskr.conf

    # App 자신의 unlock 세리모니 polkit action만 설치한다. daemon-setup.policy(계정 설치용
    # pkexec 트리거)는 NixOS 모듈이 계정을 선언적으로 만들므로 의도적으로 제외한다.
    install -Dm644 usr/share/polkit-1/actions/it.bitstep.tailpass.policy \
      $out/share/polkit-1/actions/it.bitstep.tailpass.policy

    runHook postInstall
  '';

  meta = {
    description = "Tailpass desktop app (Headscale 전용 팀 비밀 관리자) — 빌드된 .deb를 autoPatchelfHook으로 재포장";
    homepage = "https://github.com/tailpass/tailpass";
    license = lib.licenses.unfree; # 저장소에 LICENSE 파일 없음(비공개 내부 도구)
    platforms = [ "x86_64-linux" ];
    mainProgram = "tailpass-app";
  };
}
