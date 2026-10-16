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

  # 고급 관리 CLI (키워드/크기 기준 삭제, 통계, DB 최적화) — 본체는 mods/_data/clipboard/clipctl.sh
  clipctl = pkgs.writeShellScriptBin "clipctl" (
    builtins.replaceStrings
    ["@path@" "@cliphist@"]
    [
      (lib.makeBinPath [pkgs.coreutils pkgs.gnugrep pkgs.gawk pkgs.gnused pkgs.findutils pkgs.util-linux])
      cliphist
    ]
    (builtins.readFile ../../_data/clipboard/clipctl.sh)
  );

  # 클립보드 관리 TUI (Textual) — 본체는 mods/_data/clipboard/clipui.py
  # 검색(퍼지 + 내용 전체), 전문 미리보기·부분 복사, 체크 후 일괄 삭제, 통계, DB 최적화. 창 크기에 반응
  clipuiSource = pkgs.writeText "clipui.py" (
    builtins.replaceStrings
    ["@cliphist@" "@clipctl@" "@wlcopy@"]
    [cliphist "${clipctl}/bin/clipctl" wlCopy]
    (builtins.readFile ../../_data/clipboard/clipui.py)
  );
  clipui = pkgs.writeShellScriptBin "clipui" ''
    exec ${pkgs.python3.withPackages (ps: [ps.textual])}/bin/python3 ${clipuiSource} "$@"
  '';

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
    ${cliphist} decode "$ID" | ${wlCopy}
  '';
in {
  hm = {
    home.packages = [clipMenu clipctl clipui clipuiOpen];

    # 앱 런처(SUPER+Space)에서도 검색되도록 freedesktop 등록. clipui-open 이 class=clipui 전용 창으로 연다
    xdg.desktopEntries.clipui = {
      name = "클립보드 관리";
      genericName = "Clipboard Manager";
      comment = "클립보드 이력 검색 · 전문 보기 · 선택 복사 · 일괄 삭제 · DB 최적화";
      exec = "${clipuiOpen}/bin/clipui-open";
      terminal = false;
      categories = ["Utility"];
      icon = "edit-paste";
    };

    wayland.windowManager.hyprland.extraConfig = ''
      -- 클립보드 관리 TUI 창: 모니터 크기에 비례한 크기로 가운데에 (안의 내용은 창 크기에 맞춰 반응)
      hl.window_rule({
        match = { class = "^(clipui)$" },
        center = true,
        size = { "monitor_w * 0.7", "monitor_h * 0.75" }
      })
      hl.bind("SUPER + V", hl.dsp.exec_cmd("${clipMenu}/bin/hypr-cliphist"), { description = "클립보드 히스토리 (빠른 붙여넣기)" })
      hl.bind("SUPER + SHIFT + V", hl.dsp.exec_cmd("${clipuiOpen}/bin/clipui-open"), { description = "클립보드 관리 (검색·전문·삭제·최적화)" })
    '';
  };
})
