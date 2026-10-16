{mkPartOf, ...}:
mkPartOf "mods.gui" ({pkgs, ...}: let
  wofi = "${pkgs.wofi}/bin/wofi";
  cliphist = "${pkgs.cliphist}/bin/cliphist";
  wlCopy = "${pkgs.wl-clipboard}/bin/wl-copy";
  notify = "${pkgs.libnotify}/bin/notify-send";
  numfmt = "${pkgs.coreutils}/bin/numfmt";
  less = "${pkgs.less}/bin/less";
  kitty = "${pkgs.kitty}/bin/kitty";
  uwsm = "${pkgs.uwsm}/bin/uwsm";

  # 클립보드 메뉴: paste(기본) = 선택한 항목 복사, manage = 항목별 복사/전문 보기/삭제
  # 목록의 ID 는 숨기고 미리보기만 보여준 뒤, 선택한 줄 번호로 ID 를 되찾는다
  # (주의: wofi 모드 옵션은 `-D <모드>-<옵션>` 형식)
  clipMenu = pkgs.writeShellScriptBin "hypr-cliphist" ''
    # 이미 떠 있으면 닫기(토글) — Nix 래핑으로 프로세스 이름이 .wofi-wrapped
    pkill -x '(.wofi-wrapped|wofi)' && exit 0

    MODE=''${1:-paste}
    WOFI="${wofi} --dmenu --cache-file /dev/null --width 1400"

    while true; do
      LIST=$(${cliphist} -preview-width 300 list)
      if [ -z "$LIST" ]; then
        ${notify} "클립보드" "저장된 이력이 없습니다"
        exit 0
      fi

      PROMPT="클립보드 검색"
      [ "$MODE" = manage ] && PROMPT="클립보드 관리 — 항목을 고르면 복사 / 전문 보기 / 삭제"

      N=$(printf '%s\n' "$LIST" | cut -f2- | $WOFI --prompt "$PROMPT" -D dmenu-print_line_num=true) || exit 0
      [ -z "$N" ] && exit 0
      LINE=$(printf '%s\n' "$LIST" | sed -n "$((N + 1))p")
      ID=''${LINE%%$'\t'*}
      [ -z "$ID" ] && exit 0

      if [ "$MODE" != manage ]; then
        ${cliphist} decode "$ID" | ${wlCopy}
        exit 0
      fi

      SIZE=$(${cliphist} decode "$ID" | wc -c)
      HUMAN=$(${numfmt} --to=iec --suffix=B "$SIZE")
      ACTION=$(printf '복사\n전문 보기\n삭제\n' | $WOFI --prompt "#$ID · $HUMAN — 동작 선택") || continue

      case "$ACTION" in
        "복사")
          ${cliphist} decode "$ID" | ${wlCopy}
          exit 0
          ;;
        "전문 보기")
          # 큰 내용도 다룰 수 있게 pager 로 연다 (q 로 닫기)
          ${uwsm} app -- ${kitty} --title "클립보드 #$ID ($HUMAN)" \
            sh -c '${cliphist} decode "$1" | ${less}' _ "$ID"
          exit 0
          ;;
        "삭제")
          printf '%s\n' "$LINE" | ${cliphist} delete
          ${notify} -t 1500 "클립보드" "#$ID ($HUMAN) 삭제됨"
          ;;
      esac
    done
  '';
in {
  hm = {
    home.packages = [clipMenu];

    wayland.windowManager.hyprland.extraConfig = ''
      hl.bind("SUPER + V", hl.dsp.exec_cmd("${clipMenu}/bin/hypr-cliphist"), { description = "클립보드 히스토리" })
      hl.bind("SUPER + SHIFT + V", hl.dsp.exec_cmd("${clipMenu}/bin/hypr-cliphist manage"), { description = "클립보드 관리 (전문 보기/삭제)" })
    '';
  };
})
