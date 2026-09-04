/*
  tailpass-app(로드맵 F 이후 egui/eframe 네이티브 앱, 구 clients/app-native) —
  이미 빌드된 .deb(`./build.sh app`이 만든
  `target/release/bundle/deb/Tailpass_<version>_amd64.deb`)를 autoPatchelfHook으로
  재포장하는 파생물. nixpkgs의 vscode/discord류와 동일한 패턴 — tss-esapi 등 네이티브
  의존성을 Nix로 처음부터 재빌드하지 않고, 이미 검증된 Docker 기반 빌드 파이프라인
  (build.sh)의 산출물을 그대로 신뢰한다. (webview 시절 필요했던 webkitgtk_4_1/
  libsoup_3 의존성은 로드맵 F에서 webview 자체를 제거하며 함께 뺐다.)

  postinst.sh/AppRun.template이 하던 systemd 유닛·D-Bus 정책·polkit daemon-setup
  action·계정 생성은 이 파생물에 포함하지 않는다 — deploy/nix/modules/{daemon,authagent}.nix
  NixOS 모듈이 선언적으로 대체한다. daemon-setup.policy(계정 설치용 pkexec 트리거)는
  NixOS 배포에서 완전히 무의미하므로 설치하지 않는다.

  .deb 안의 실제 파일 배치는 `dpkg-deb -x`로 실측 확인했다(이 파일 배치는
  clients/app/Cargo.toml의 [package.metadata.packager.deb]/externalBinaries
  설정 + deploy/inject-deb-scripts.sh가 만드는데, 최종 산출물로 어디에 떨어지는지는
  소스만 봐서는 알 수 없어 실제 .deb를 풀어 확인함).
*/
{ lib
, stdenv
, autoPatchelfHook
, makeWrapper
, dpkg
, gtk3
, glib
, cairo
, gdk-pixbuf
, dbus
, tpm2-tss
, systemd
, libayatana-appindicator
, wayland
, libxkbcommon
, libGL
, xdg-utils
, desktop-file-utils
, xdotool
, runCommand
, debSrc
}:

# tailpass-app(Docker/Ubuntu 22.04 빌드)이 링크한 libxdo.so.3를 채워주는 호환
# 심볼릭 링크. nixpkgs 리비전에 따라 xdotool 패키지가 제공하는 SONAME이
# libxdo.so.3(구버전 xdotool 3.x, 이 심볼릭 링크가 사실상 불필요)이거나
# libxdo.so.4(신버전 xdotool 4.x)일 수 있어 — 실제로 이 저장소의 flake.lock
# 고정 리비전(753cc8a3a874)은 4.x인데, `nix flake update`로 갱신되는 다른 환경
# (예: ~/nixos)의 nixpkgs-unstable은 여전히 3.x였다 — 둘 다 대응하도록 실제
# 존재하는 파일을 찾아 링크한다. muda(tray-icon의 전이 의존성)가 쓰는 libxdo
# API 표면은 xdo_new/xdo_get_active_window 등 오래 안정적인 소수 함수뿐이라
# 3.x→4.x 사이에서도 동작할 가능성이 높다고 보지만, **실제 ABI 호환성은
# 검증하지 못했다** — 트레이 아이콘 클릭/메뉴 동작을 실기에서 반드시 확인할 것.
let
  libxdoCompat = runCommand "libxdo-compat" { } ''
    mkdir -p $out/lib
    if [ -e "${xdotool}/lib/libxdo.so.3" ]; then
      ln -s "${xdotool}/lib/libxdo.so.3" $out/lib/libxdo.so.3
    elif [ -e "${xdotool}/lib/libxdo.so.4" ]; then
      ln -s "${xdotool}/lib/libxdo.so.4" $out/lib/libxdo.so.3
    else
      echo "libxdo-compat: ${xdotool}에서 libxdo.so.{3,4}를 찾지 못했습니다" >&2
      exit 1
    fi
  '';
in

stdenv.mkDerivation {
  pname = "tailpass-app";
  # .deb 파일명(Tailpass_<version>_amd64.deb)에서 버전을 뽑아낼 수도 있지만, debSrc가
  # 임의 로컬 경로로 주입되므로(로컬 경로 입력 방식, GitHub Release fetchurl 아님) 파일명
  # 규칙에 의존하지 않는다.
  version = "local";

  src = debSrc;

  nativeBuildInputs = [ autoPatchelfHook makeWrapper dpkg ];

  # ldd 실측 기반 (tailpass-app, tailpass-authagent, tailpass-ceremony의 미해결 의존성).
  # tailpass-daemon/tailpass-daemon-nm/tailpass-cli/tailpass-sshagent는 glibc/libgcc뿐이라
  # 추가 buildInputs 불필요 — autoPatchelfHook이 자동으로 처리한다(sshagent는 egui/GUI
  # 의존성이 전혀 없는 순수 백그라운드 프로세스라 daemon류와 동일 계열).
  buildInputs = [
    gtk3
    glib
    cairo
    gdk-pixbuf
    dbus
    tpm2-tss
    systemd # libudev.so.1 (tailpass-ceremony)
    # libxdo.so.3 — tray-icon(egui 네이티브 앱)의 전이 의존성 muda가 링크하는
    # ELF NEEDED 라이브러리(dlopen이 아니라 실제 링크 의존성이라 autoPatchelfHook이
    # 직접 잡아냄). webview 시절엔 Tauri의 tray 구현이 이 의존성을 요구하지 않아
    # package.nix에 없었는데, 로드맵 F 전환 후 처음 nix 빌드를 시도하며 발견됐다.
    # 이 flake.lock 리비전의 xdotool 패키지는 libxdo.so.4만 제공해(SONAME 불일치)
    # 위 libxdoCompat 심볼릭 링크 파생물을 대신 buildInputs에 넣는다.
    libxdoCompat
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
  # (역사적 기록 — 로드맵 F 이전 webview tailpass-app 시절의 조사) 한때
  # WEBKIT_DISABLE_COMPOSITING_MODE/WEBKIT_DISABLE_DMABUF_RENDERER를 UI가 흰
  # 사각형으로 렌더링되던 문제의 표준 우회책으로 넣었었으나, 실기 확인 결과 진짜
  # 원인은 아래 __EGL_VENDOR_LIBRARY_DIRS 미설정이었다(이 버그 조사가 결국
  # `_metadocs/claude/plan/roadmap/app-native-ui-migration.md`의 webview 제거
  # 결정으로 이어졌다). webview 자체는 로드맵 F에서 제거됐지만, tailpass-app이
  # 지금은 egui/glow(OpenGL)로 렌더링하므로 EGL vendor dir 문제 자체는 여전히
  # 유효한 우려라 이 픽스는 유지한다 — glow도 GLVND를 거치는 동일 계열 렌더
  # 경로이기 때문.
  #
  # AppImage(deploy/AppRun.template)와의 결정적 차이: AppRun은
  # `/run/opengl-driver/share/glvnd/egl_vendor.d`(NixOS가 실제 GPU 드라이버에 맞춰
  # 관리하는 GLVND EGL vendor ICD 심볼릭 링크, hardware.graphics.enable)를
  # __EGL_VENDOR_LIBRARY_DIRS로 명시한다. 이게 없으면 GLVND가 이 패키지에 딸려온
  # nixpkgs 범용 libGL/Mesa의 기본 vendor.d(호스트의 실제 GPU 드라이버와 다를 수
  # 있음)로 폴백해 EGL 컴포지팅 경로가 스케일 팩터를 잘못 계산할 수 있다.
  # /run/opengl-driver는 빌드 시점이 아니라 대상 머신에서만 존재 여부를 알 수
  # 있으므로 --set(빌드 시 고정값)이 아니라 --run(실행 시 조건부 export)으로 넣는다.
  #
  # GSETTINGS_SCHEMA_DIR — 실기 확인된 크래시(GLib-GIO-ERROR "No GSettings
  # schemas are installed on the system", G_LOG_LEVEL_ERROR라 즉시 abort):
  # PEM 업로드 파일 다이얼로그(rfd의 gtk3 백엔드, GtkFileChooserDialog)가
  # `org.gtk.Settings.FileChooser` 스키마를 조회하는데, 이 파생물은
  # `wrapGAppsHook3`(nixpkgs가 GTK 앱에 흔히 쓰는 표준 훅 — buildInputs를
  # 스캔해 GSETTINGS_SCHEMA_DIR/XDG_DATA_DIRS를 자동으로 채워줌) 없이
  # autoPatchelfHook + 수동 wrapProgram만 쓰므로 이 환경변수가 통째로 비어
  # 있었다. wrapGAppsHook3를 새로 얹으면 이미 있는 수동 wrapProgram 호출과
  # 순서/중복 문제가 생길 수 있어(둘 다 $out/bin/*를 wrapProgram으로 감쌈),
  # 이미 buildInputs에 있는 gtk3의 스키마 경로만 정확히 짚어 직접 주입하는
  # 쪽을 택한다. `glib.getSchemaPath`는 버전 문자열을 하드코딩하지 않고
  # `${pkg}/share/gsettings-schemas/${pkg.name}/glib-2.0/schemas`를 계산해주는
  # nixpkgs 표준 헬퍼라 gtk3 버전이 올라가도 깨지지 않는다(직접
  # `nix eval`로 실측: `${gtk3}/share/gsettings-schemas/gtk+3-<ver>/glib-2.0/schemas/gschemas.compiled`
  # 안에 org.gtk.Settings.FileChooser.gschema.xml 포함 확인).
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
    gtk3SchemaPath = glib.getSchemaPath gtk3;
  in ''
    wrapProgram $out/bin/tailpass-app \
      --prefix LD_LIBRARY_PATH : ${runtimeLibPath} \
      --prefix PATH : ${lib.makeBinPath [ xdg-utils desktop-file-utils ]} \
      --set GSETTINGS_SCHEMA_DIR ${lib.escapeShellArg gtk3SchemaPath} \
      --run ${lib.escapeShellArg eglVendorRunSnippet}
    wrapProgram $out/bin/tailpass-ceremony \
      --prefix LD_LIBRARY_PATH : ${runtimeLibPath} \
      --set GSETTINGS_SCHEMA_DIR ${lib.escapeShellArg gtk3SchemaPath} \
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
      usr/bin/tailpass-ceremony \
      usr/bin/tailpass-sshagent

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
