{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  pkgs,
  lib,
  ...
}: let
  wofi = "${pkgs.wofi}/bin/wofi";
  cliphist = "${pkgs.cliphist}/bin/cliphist";
  wlCopy = "${pkgs.wl-clipboard}/bin/wl-copy";
  notify = "${pkgs.libnotify}/bin/notify-send";
  kitty = "${pkgs.kitty}/bin/kitty";
  uwsm = "${pkgs.uwsm}/bin/uwsm";

  hyprctl = "${pkgs.hyprland}/bin/hyprctl";
  py = pkgs.python3.withPackages (ps: [ps.textual]);
  src = name: builtins.readFile (../../_tools/desktop/clipboard + "/${name}");

  # 부가 정보(시각·출처 앱·복사/사용 횟수) 사이드카 — clipmeta.py (cliphist DB 형식은 그대로 두고 옆에 sqlite 로 기록)
  # 파이썬 import 가 되도록 세 스크립트(clipmeta/clipstore/clipui)는 같은 디렉터리에 둔다
  clipmetaDir = pkgs.runCommand "clipboard-py" {} ''
    mkdir -p $out
    cp ${pkgs.writeText "clipmeta.py" (builtins.replaceStrings ["@cliphist@" "@hyprctl@"] [cliphist hyprctl] (src "clipmeta.py"))} $out/clipmeta.py
    cp ${pkgs.writeText "clipstore.py" (src "clipstore.py")} $out/clipstore.py
  '';
  clipmeta = pkgs.writeShellScriptBin "clipmeta" ''exec ${py}/bin/python3 ${clipmetaDir}/clipmeta.py "$@"'';

  # wl-paste --watch 가 클립보드가 바뀔 때마다 호출: cliphist 에 저장(기존 동작) + 부가 정보 기록
  clipstore = pkgs.writeShellScriptBin "clipstore" ''exec ${py}/bin/python3 ${clipmetaDir}/clipstore.py "$@"'';

  # 고급 관리 CLI (키워드/크기 기준 삭제, 통계, DB 최적화) — 본체는 mods/_tools/desktop/clipboard/clipctl.sh
  clipctl = pkgs.writeShellScriptBin "clipctl" (
    builtins.replaceStrings
    ["@path@" "@cliphist@" "@clipmeta@"]
    [
      (lib.makeBinPath [pkgs.coreutils pkgs.gnugrep pkgs.gawk pkgs.gnused pkgs.findutils pkgs.util-linux])
      cliphist
      "${clipmeta}/bin/clipmeta"
    ]
    (src "clipctl.sh")
  );

  # 클립보드 관리 TUI (Textual) — 본체는 mods/_tools/desktop/clipboard/clipui.py
  # 검색(퍼지 + 내용 전체 + 필터), 전문 미리보기·부분 복사, 체크 후 일괄 삭제, 풍부한 통계, DB 최적화. 창 크기에 반응
  # clipmeta.py 를 import 하므로 clipmetaDir 와 같은 디렉터리에 복사해 둔다
  clipuiDir = pkgs.runCommand "clipui-py" {} ''
    mkdir -p $out
    cp ${clipmetaDir}/clipmeta.py $out/clipmeta.py
    cp ${../../_tools/_lib/uikit/uikit.py} $out/uikit.py
    cp ${pkgs.writeText "clipui.py" (builtins.replaceStrings ["@clipctl@" "@wlcopy@"] ["${clipctl}/bin/clipctl" wlCopy] (src "clipui.py"))} $out/clipui.py
  '';
  clipui = pkgs.writeShellScriptBin "clipui" ''exec ${py}/bin/python3 ${clipuiDir}/clipui.py "$@"'';

  # 전용 창(class=clipui)으로 열기 — 이미 떠 있으면 새로 띄우지 않고 그 창으로 포커스
  # (창 크기/위치는 아래 window_rule 이 class 로 지정)
  clipuiOpen = pkgs.writeShellScriptBin "clipui-open" ''
    if hyprctl clients -j | ${pkgs.jq}/bin/jq -e '.[] | select(.class == "clipui")' >/dev/null 2>&1; then
      exec hyprctl dispatch 'hl.dsp.focus({ window = "class:^clipui$" })'
    fi
    exec ${uwsm} app -- ${kitty} --class clipui --title "클립보드 관리" ${clipui}/bin/clipui
  '';

  # 빠른 붙여넣기: wofi 로 항목을 고르면 복사 (번호 ID 는 숨기고 미리보기만 표시)
  # (주의: wofi 모드 옵션은 `-D <모드>-<옵션>` 형식)
  clipMenu = pkgs.writeShellScriptBin "hypr-cliphist" ''
    # 이미 떠 있으면 닫기(토글) — Nix 래핑으로 프로세스 이름이 .wofi-wrapped
    pkill -x '(.wofi-wrapped|wofi)' && exit 0

    LIST=$(${cliphist} -preview-width 300 list)
    if [ -z "$LIST" ]; then
      ${notify} "클립보드" "저장된 이력이 없습니다"
      exit 0
    fi

    N=$(printf '%s\n' "$LIST" | cut -f2- \
      | ${wofi} --dmenu --cache-file /dev/null --width 1400 --prompt "클립보드 검색" -D dmenu-print_line_num=true) || exit 0
    [ -z "$N" ] && exit 0
    ID=$(printf '%s\n' "$LIST" | sed -n "$((N + 1))p" | cut -f1)
    [ -z "$ID" ] && exit 0
    ${clipmeta}/bin/clipmeta use "$ID" 2>/dev/null || true
    ${cliphist} decode "$ID" | ${wlCopy}
  '';
in {
  hm = {
    home.packages = [clipMenu clipctl clipui clipuiOpen clipmeta clipstore];

    # 수집 서비스: cliphist 에 저장(기존 동작) + 시각·출처 앱·복사 횟수 기록 (wl-clip.nix 의 ExecStart 를 대체)
    systemd.user.services.cliphist.Service.ExecStart = lib.mkForce "${pkgs.wl-clipboard}/bin/wl-paste --type text/plain --watch ${clipstore}/bin/clipstore";

    # 앱 런처(SUPER+Space)에서도 검색되도록 freedesktop 등록. clipui-open 이 class=clipui 전용 창으로 연다
    xdg.desktopEntries.clipui = {
      # (런처에 보이는 이름은 다른 앱들처럼 영어로 통일)
      name = "Clipboard Manager";
      genericName = "Clipboard history";
      comment = "Search, preview, copy parts of, bulk-delete and optimize the clipboard history";
      exec = "${clipuiOpen}/bin/clipui-open";
      terminal = false;
      categories = ["Utility"];
      icon = "edit-paste";
    };

    wayland.windowManager.hyprland.extraConfig = ''
      -- 클립보드 관리 TUI 창: 모니터 크기에 비례한 크기로 가운데에 (안의 내용은 창 크기에 맞춰 반응)
      -- 열기: 앱 런처(SUPER+Space)에서 "Clipboard Manager" — 전용 단축키는 두지 않음
      hl.window_rule({
        match = { class = "^(clipui)$" },
        center = true,
        size = { "monitor_w * 0.7", "monitor_h * 0.75" }
      })
      hl.bind("SUPER + V", hl.dsp.exec_cmd("${clipMenu}/bin/hypr-cliphist"), { description = "클립보드 히스토리 (빠른 붙여넣기)" })
    '';
  };
})
