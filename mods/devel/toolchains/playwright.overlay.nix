# Playwright Overlay
# 목적: CDN chromium-headless-shell이 LD_LIBRARY_PATH를 통해 동작하도록
#       playwright 실행 체인 전체에 chromium 의존 libs를 self-contained로 주입한다.
#
# 체인:
#   playwright-wrapped (LD_LIBRARY_PATH=chromiumLibs, PATH=node-passthrough:...)
#     → pnpm shim (exec node cli.js)
#       → node-passthrough (bare nodejs_24, LD_LIBRARY_PATH 상속)
#         → playwright JS
#           → chromium subprocess (chromiumLibs 상속) ✓
#
# 핵심1: CDN chromium 바이너리의 ELF interpreter가 이미 nix glibc를 직접 가리킴
#        → nix-ld 우회 → NIX_LD_LIBRARY_PATH 무시 → LD_LIBRARY_PATH 필요
# 핵심2: node-passthrough를 bins로 PATH 앞에 주입해 shim이 부르는 'node'가
#        node-wrapped(--set으로 덮어씀) 대신 bare nodejs_24를 찾도록 한다.
# 핵심3: shim 탐색 시 현재 디렉터리부터 루트까지 올라가며 node_modules를 찾음
#        → 프로젝트 서브디렉터리 또는 외부 스크립트 디렉터리에서도 동작
_final: prev: let
  # bare node passthrough — node-wrapped를 거치지 않아 LD_LIBRARY_PATH를 상속받음
  nodePassthrough = prev.writeShellScriptBin "node" ''
    exec ${prev.nodejs_24}/bin/node "$@"
  '';

  # playwright 진입점 — 현재 디렉터리부터 루트까지 올라가며 node_modules/.bin/playwright 탐색
  playwrightRunner = prev.writeShellScriptBin "playwright" ''
    dir="$(pwd)"
    shim=""
    while [ "$dir" != "/" ]; do
      if [ -f "$dir/node_modules/.bin/playwright" ]; then
        shim="$dir/node_modules/.bin/playwright"
        break
      fi
      dir="$(dirname "$dir")"
    done
    if [ -z "$shim" ]; then
      echo "playwright: node_modules/.bin/playwright not found (상위 디렉터리 포함 탐색 실패)" >&2
      exit 1
    fi
    exec "$shim" "$@"
  '';

  # CDN chromium 바이너리는 interpreter가 이미 nix glibc를 직접 가리키므로
  # nix-ld 우회 → NIX_LD_LIBRARY_PATH 무시. 실제 glibc가 읽는 LD_LIBRARY_PATH 사용.
  chromiumLibs = prev.lib.makeLibraryPath (with prev; [
    stdenv.cc.cc
    openssl
    glib
    nss
    nspr
    dbus
    at-spi2-core
    at-spi2-atk
    cups
    libdrm
    libgbm
    expat
    alsa-lib
    libxkbcommon
    pango
    cairo
    fontconfig
    freetype
    libxml2
    zlib
    # X11 / XCB — headless 모드에서도 Chromium이 요구하는 라이브러리들
    libxcb
    libxext
    libx11
    libxcomposite
    libxdamage
    libxfixes
    libxrandr
    libxrender
    libxi
    libxtst
    libxshmfence
    libxau
    libxdmcp
    libxcursor
  ]);
in {
  playwright-wrapped = prev.mkWrapper {
    pkg = playwrightRunner;
    env = {
      LD_LIBRARY_PATH = chromiumLibs;
    };
    bins = with prev; [
      nodePassthrough # shim의 'exec node ...'가 bare node로 해석되도록 PATH 앞에 주입
      xdg-utils # chromium 링크 오픈
      dbus # dbus-launch
    ];
  };
}
