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
  numfmt = "${pkgs.coreutils}/bin/numfmt";
  less = "${pkgs.less}/bin/less";
  kitty = "${pkgs.kitty}/bin/kitty";
  uwsm = "${pkgs.uwsm}/bin/uwsm";
  gawk = "${pkgs.gawk}/bin/gawk";
  zenity = "${pkgs.zenity}/bin/zenity";

  # 고급 관리 CLI (키워드/크기 기준 일괄 삭제, 통계, DB 최적화) — 본체는 mods/_data/clipboard/clipctl.sh
  clipctl = pkgs.writeShellScriptBin "clipctl" (
    builtins.replaceStrings
    ["@path@" "@cliphist@"]
    [
      (lib.makeBinPath [pkgs.coreutils pkgs.gnugrep pkgs.gawk pkgs.gnused pkgs.findutils pkgs.util-linux])
      cliphist
    ]
    (builtins.readFile ../../_data/clipboard/clipctl.sh)
  );
  ctl = "${clipctl}/bin/clipctl";

  # 클립보드 메뉴: paste(기본) = 선택한 항목 복사, manage = 항목별 복사/전문 보기/삭제 + 일괄 작업
  # 목록의 ID 는 숨기고 미리보기만 보여준 뒤, 선택한 줄 번호로 ID 를 되찾는다
  # (주의: wofi 모드 옵션은 `-D <모드>-<옵션>` 형식)
  clipMenu = pkgs.writeShellScriptBin "hypr-cliphist" ''
    # 이미 떠 있으면 닫기(토글) — Nix 래핑으로 프로세스 이름이 .wofi-wrapped
    pkill -x '(.wofi-wrapped|wofi)' && exit 0

    MODE=''${1:-paste}
    WOFI="${wofi} --dmenu --cache-file /dev/null --width 1400"

    # zenity(GTK 대화상자): wofi 는 목록 선택용이라 입력창·진행 표시·항목별 체크를 못 함
    # (GTK 테마 경고가 stderr 로 나오므로 버림)
    z() { ${zenity} "$@" 2>/dev/null; }

    # zenity --text 는 마크업이라 &, <, > 를 이스케이프
    esc() { sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }

    # 오래 걸리는 명령을 실행하는 동안 진행 표시줄(취소 가능)을 보여준다. 결과(stdout)는 $SPIN_OUT 에 담는다
    # 반환: 0 = 끝까지 실행, 1 = 사용자가 취소 (취소하면 실행 중인 명령도 중단)
    # SPIN_NOCANCEL=1 이면 취소 버튼을 없앤다 (DB 최적화처럼 중간에 끊기면 곤란한 작업용)
    spin() {
      local text="$1" out pid zpid zopts=()
      shift
      [ "''${SPIN_NOCANCEL:-0}" = 1 ] && zopts+=(--no-cancel)
      out=$(mktemp)
      "$@" >"$out" 2>/dev/null &
      pid=$!
      # 명령이 끝나면 입력이 닫혀 진행 창이 저절로 닫힘
      ( while kill -0 "$pid" 2>/dev/null; do sleep 0.2; done ) \
        | z --progress --pulsate --auto-close "''${zopts[@]}" --title "클립보드" --text "$text" --width 400 &
      zpid=$!
      while kill -0 "$pid" 2>/dev/null && kill -0 "$zpid" 2>/dev/null; do sleep 0.2; done
      if kill -0 "$pid" 2>/dev/null; then
        # 명령이 아직 도는데 진행 창이 먼저 닫힘 = 사용자가 취소
        kill "$pid" 2>/dev/null
        wait "$pid" 2>/dev/null
        rm -f "$out"
        return 1
      fi
      wait "$zpid" 2>/dev/null
      SPIN_OUT=$(cat "$out")
      rm -f "$out"
      return 0
    }

    # 삭제 확인: $1 = 문구, $2 = "id<TAB>바이트<TAB>미리보기" 목록. 체크박스로 삭제할 항목을 고른다 (기본: 전부 체크)
    # 선택이 있으면 0 을 반환하고 체크한 항목만 $ROWS 에 남긴다
    # (주의: 파이프 오른쪽에서 호출하면 서브셸이라 $ROWS 가 부모 셸에 전달되지 않으므로 인자로 받는다)
    confirm_checklist() {
      local rows="$2" n sel
      if [ -z "$rows" ]; then
        ${notify} -t 2500 "클립보드" "일치하는 항목이 없습니다"
        return 1
      fi
      n=$(printf '%s\n' "$rows" | wc -l)
      sel=$(printf '%s\n' "$rows" | while IFS=$'\t' read -r id bytes preview; do
          printf 'TRUE\n%s\n%s\n%s\n' "$id" "$(${numfmt} --to=iec --suffix=B "$bytes")" "$preview"
        done | z --list --checklist --title "클립보드 일괄 삭제 — 확인" \
          --text "$(printf '%s' "$1" | esc) — 총 ''${n}개. 삭제할 항목만 체크하세요 (기본: 전부 체크)" \
          --column "삭제" --column "ID" --column "크기" --column "미리보기" \
          --print-column 2 --separator "," \
          --ok-label "체크한 항목 삭제" --cancel-label "취소" --width 1200 --height 720) || return 1
      [ -z "$sel" ] && return 1
      ROWS=$(printf '%s\n' "$rows" | ${gawk} -F'\t' -v ids=",$sel," 'index(ids, "," $1 ",") > 0')
      [ -z "$ROWS" ] && return 1
      return 0
    }

    delete_rows() {
      printf '%s\n' "$ROWS" | cut -f1,3 | ${cliphist} delete
      ${notify} -t 2500 "클립보드" "$(printf '%s\n' "$ROWS" | wc -l)개 삭제됨"
    }

    # 항목 상세: 동작(전체 복사/삭제/pager)과 전문을 줄 단위 항목으로 함께 보여준다.
    # 줄을 고르면 그 줄만 복사하고, Esc 는 목록으로 돌아간다.
    # 반환: 0 = 복사해서 끝냄, 1 = 목록으로 돌아감
    # (표시 제한: 많은 줄/긴 줄은 wofi 가 무거워지므로 잘라서 보여주고 전체는 pager 로)
    MAX_LINES=300
    MAX_WIDTH=1500
    detail_menu() {
      local tmp total shown pick k status
      tmp=$(mktemp)
      ${cliphist} decode "$ID" > "$tmp"
      total=$(${gawk} 'END { print NR }' "$tmp")
      shown=$total
      [ "$shown" -gt "$MAX_LINES" ] && shown=$MAX_LINES

      while true; do
        pick=$({
          printf '전체 복사\n'
          printf '이 항목 삭제\n'
          printf '별도 창(pager)에서 전문 열기\n'
          printf '── 전문 · %s줄 · %s — 줄을 고르면 그 줄만 복사 ──\n' "$total" "$HUMAN"
          ${gawk} -v max="$MAX_LINES" -v w="$MAX_WIDTH" '
            NR > max { exit }
            { l = $0
              if (l == "") l = " "
              else if (length(l) > w) l = substr(l, 1, w) " … (이하 생략)"
              print l }' "$tmp"
          if [ "$total" -gt "$MAX_LINES" ]; then
            printf '… 외 %s줄 생략 — 전체는 위의 pager 로 여세요\n' "$((total - MAX_LINES))"
          fi
        } | $WOFI -D line_wrap=word --prompt "#$ID 전문 — 동작을 고르세요 (Esc: 목록으로)" -D dmenu-print_line_num=true)
        status=$?
        if [ "$status" -ne 0 ] || [ -z "$pick" ]; then rm -f "$tmp"; return 1; fi

        case "$pick" in
          0) ${wlCopy} < "$tmp"; rm -f "$tmp"; return 0 ;;
          1)
            printf '%s\n' "$LINE" | ${cliphist} delete
            ${notify} -t 1500 "클립보드" "#$ID ($HUMAN) 삭제됨"
            rm -f "$tmp"; return 1 ;;
          2)
            # pager 가 닫힐 때까지 기다렸다가 이 화면으로 돌아옴
            ${uwsm} app -- ${kitty} --title "클립보드 #$ID ($HUMAN)" \
              sh -c '${cliphist} decode "$1" | ${less}' _ "$ID"
            ;;
          3) ;;
          *)
            k=$((pick - 3))
            if [ "$k" -ge 1 ] && [ "$k" -le "$shown" ]; then
              printf '%s' "$(${gawk} -v n="$k" 'NR == n { print; exit }' "$tmp")" | ${wlCopy}
              rm -f "$tmp"; return 0
            fi
            ;;
        esac
      done
    }

    # 일괄 작업 메뉴
    tools_menu() {
      local choice kw kb
      choice=$(printf '%s\n' \
        '키워드로 일괄 삭제' '큰 항목 삭제' '통계 보기' 'DB 최적화 (파일 크기 줄이기)' '전체 삭제' \
        | $WOFI --prompt "일괄 작업") || return 0

      case "$choice" in
        "키워드로 일괄 삭제")
          kw=$(z --entry --title "클립보드 일괄 삭제 — 입력" \
            --text "삭제할 키워드를 입력하세요 (대소문자 구분 없음, 항목 내용 전체에서 검색)" \
            --width 520 --ok-label "검색" --cancel-label "취소") || return 0
          [ -z "$kw" ] && return 0
          spin "'$(printf '%s' "$kw" | esc)' 검색 중…" ${ctl} find "$kw" --tsv || return 0
          if confirm_checklist "'$kw' 포함 항목" "$SPIN_OUT"; then delete_rows; fi
          ;;
        "큰 항목 삭제")
          kb=$(z --entry --title "클립보드 일괄 삭제 — 입력" --entry-text 10 \
            --text "이 크기(KB) 이상인 항목을 찾습니다" \
            --width 420 --ok-label "검색" --cancel-label "취소") || return 0
          case "$kb" in *[!0-9]*|"") ${notify} "클립보드" "숫자(KB)를 입력하세요"; return 0 ;; esac
          spin "''${kb}KB 이상 항목을 찾는 중…" ${ctl} big "$kb" --tsv || return 0
          if confirm_checklist "''${kb}KB 이상 항목" "$SPIN_OUT"; then delete_rows; fi
          ;;
        "통계 보기")
          spin "통계를 계산하는 중…" ${ctl} stats || return 0
          printf '%s\n' "$SPIN_OUT" | z --text-info --title "클립보드 통계" --width 700 --height 420 --font "monospace 11"
          ;;
        "DB 최적화 (파일 크기 줄이기)")
          z --question --title "DB 최적화" --width 520 --ok-label "최적화 실행" --cancel-label "취소" \
            --text "클립보드 DB 를 새로 구성합니다. 백업이 자동으로 만들어지고 이력 번호는 새로 매겨집니다. 수 초 걸리며 그동안 새 복사는 기록되지 않습니다." || return 0
          SPIN_NOCANCEL=1 spin "DB 를 최적화하는 중… (그동안 새 복사는 기록되지 않습니다)" sh -c '${ctl} compact 2>&1' || return 0
          z --info --title "DB 최적화 결과" --width 620 --text "$(printf '%s' "$SPIN_OUT" | esc)"
          ;;
        "전체 삭제")
          z --question --title "전체 삭제" --width 420 --ok-label "전부 삭제" --cancel-label "취소" \
            --text "이력 $(${cliphist} list | wc -l)개를 전부 삭제합니다. 되돌릴 수 없습니다." || return 0
          ${cliphist} wipe
          ${notify} -t 2500 "클립보드" "전체 삭제됨"
          ;;
      esac
    }

    while true; do
      LIST=$(${cliphist} -preview-width 300 list)
      if [ -z "$LIST" ]; then
        ${notify} "클립보드" "저장된 이력이 없습니다"
        exit 0
      fi

      if [ "$MODE" = manage ]; then
        # 맨 위 행(0번)은 일괄 작업, 이후 행(k번)은 이력의 k번째 줄
        N=$({
          printf '일괄 작업 (키워드로 삭제 · 큰 항목 정리 · 통계 · DB 최적화)…\n'
          printf '%s\n' "$LIST" | cut -f2-
        } | $WOFI --prompt "클립보드 관리 — 항목을 고르면 복사 / 전문 보기 / 삭제" -D dmenu-print_line_num=true) || exit 0
        [ -z "$N" ] && exit 0
        if [ "$N" = 0 ]; then
          tools_menu
          continue
        fi
        LINE=$(printf '%s\n' "$LIST" | sed -n "''${N}p")
      else
        N=$(printf '%s\n' "$LIST" | cut -f2- | $WOFI --prompt "클립보드 검색" -D dmenu-print_line_num=true) || exit 0
        [ -z "$N" ] && exit 0
        LINE=$(printf '%s\n' "$LIST" | sed -n "$((N + 1))p")
      fi
      ID=''${LINE%%$'\t'*}
      [ -z "$ID" ] && exit 0

      if [ "$MODE" != manage ]; then
        ${cliphist} decode "$ID" | ${wlCopy}
        exit 0
      fi

      SIZE=$(${cliphist} decode "$ID" | wc -c)
      HUMAN=$(${numfmt} --to=iec --suffix=B "$SIZE")
      detail_menu && exit 0
    done
  '';
in {
  hm = {
    home.packages = [clipMenu clipctl];

    wayland.windowManager.hyprland.extraConfig = ''
      hl.window_rule({ match = { class = "^(zenity)$" }, center = true })
      hl.bind("SUPER + V", hl.dsp.exec_cmd("${clipMenu}/bin/hypr-cliphist"), { description = "클립보드 히스토리" })
      hl.bind("SUPER + SHIFT + V", hl.dsp.exec_cmd("${clipMenu}/bin/hypr-cliphist manage"), { description = "클립보드 관리 (전문 보기/삭제/일괄 작업)" })
    '';
  };
})
