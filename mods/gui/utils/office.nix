# MS Office 문서(docx/xlsx/pptx) 열람·편집용 오피스 — ONLYOFFICE Desktop Editors (LibreOffice 는 주석 처리해 둠).
# 폰트: MS 전용 폰트(Calibri/Cambria 등)는 재배포할 수 없어 같은 글자 폭(metric-compatible)의 대체 폰트를 둠.
#   Calibri → Carlito, Cambria → Caladea, Arial/Times New Roman/Courier New → Liberation.
#   한글 문서는 맑은 고딕 등을 Noto CJK 로 대체하므로 글자 폭이 달라 줄바꿈 위치가 조금 달라질 수 있음.
# 실제 Windows 폰트(재배포 불가라 레포에는 없음): 이 PC 의 Windows 파티션(nvme0n1p3 NTFS)에서 직접 복사해 둠.
#   절차: udisksctl mount -b /dev/nvme0n1p3 -o ro (관리자 인증 필요) → <마운트>/Windows/Fonts 에서
#   arial/times/cour/calibri/cambria/consola/segoeui/malgun/batang/gulim/georgia/verdana/tahoma/trebuc 등
#   (*.ttf, *.ttc)을 ~/.local/share/fonts 에 "실제 파일"로 복사 → 언마운트. ONLYOFFICE 는 다음 실행 때 자동 재스캔.
#   (홈을 새로 만들면 위 절차를 다시 해야 함. 없어도 위의 호환 폰트로 대체되어 열리긴 함)
# ONLYOFFICE 의 한글: 문서 본문은 자체 렌더링 엔진이 그리는데, 이 엔진은 시스템 폰트(fontconfig)가 아니라
#   자기가 스캔한 폰트만 씀. 스캔 대상은 번들 폰트 + /usr/share/fonts(FHS) + ~/.local/share/fonts 인데,
#   변수형 .otf.ttc(Noto CJK)와 심볼릭 링크는 건너뛰어서 한글이 □ 로 나왔음(실제 시험으로 확인).
#   → 정적 TTF(나눔, Liberation)를 ~/.local/share/fonts 에 "실제 파일"로 복사해야 하므로 home-manager 의 링크 방식 대신 활성화 때 복사.
#   LibreOffice 는 fontconfig 를 직접 써서 이 문제가 없음.
{mkModOf, ...}:
mkModOf "mods.gui" __curPos "Office (ONLYOFFICE + MS 호환 폰트)" ({
  pkgs,
  lib,
  ...
}: let
  # UI 배율: ONLYOFFICE 는 기본으로 2배(창 2400x1480)로 떠서 너무 큼. 1 / 1.25 / 1.5 / 1.75 / 2 중 선택 (여기서만 바꾸면 됨)
  # 인자(--force-scale)로만 지정 가능해서, 실행 파일과 .desktop(문서 더블클릭 시 실행) 둘 다 이 값으로 감싼다.
  uiScale = "1";
  # 문서가 지정했는데 이 PC 에 없는 글꼴 → Pretendard 의 같은 굵기로 연결(이름표만 바꾼 복사본). 이유와 방법은 _tools/office-fonts/alias.py 참고.
  # 목록은 실제로 열어 본 문서(pptx)에서 나온 이름이고, 다른 문서에서 대체 글꼴로 보이는 이름이 생기면 여기에 추가.
  pretendardDir = "${pkgs.pretendard}/share/fonts/opentype";
  fontAliasMap = {
    "KoPub돋움체 Light" = "Light";
    "KoPub돋움체 Medium" = "Medium";
    "KoPub돋움체 Bold" = "Bold";
    "에스코어 드림 1 Thin" = "Thin";
    "에스코어 드림 2 ExtraLight" = "ExtraLight";
    "에스코어 드림 3 Light" = "Light";
    "에스코어 드림 4 Regular" = "Regular";
    "에스코어 드림 5 Medium" = "Medium";
    "에스코어 드림 6 Bold" = "Bold";
    "에스코어 드림 7 ExtraBold" = "ExtraBold";
    "에스코어 드림 8 Heavy" = "Black";
    "에스코어 드림 9 Black" = "Black";
    "산돌고딕B" = "Bold";
  };
  fontAliases =
    pkgs.runCommand "office-font-aliases" {
      nativeBuildInputs = [(pkgs.python3.withPackages (p: [p.fonttools]))];
    } ''
      python3 -I ${../../_tools/office-fonts/alias.py} $out \
        ${lib.concatStringsSep " \\\n      " (lib.mapAttrsToList (n: w: lib.escapeShellArg "${n}=${pretendardDir}/Pretendard-${w}.otf") fontAliasMap)}
    '';
  onlyoffice = pkgs.symlinkJoin {
    name = "onlyoffice-desktopeditors-scaled";
    paths = [pkgs.onlyoffice-desktopeditors];
    nativeBuildInputs = [pkgs.makeWrapper];
    postBuild = ''
      rm $out/bin/onlyoffice-desktopeditors
      # ONLYOFFICE 는 bubblewrap 으로 만든 FHS 환경(buildFHSEnv)이라, Hyprland 가 자식에게 물려주는 ambient CAP_SYS_NICE 가 있으면
      # bwrap 이 "Unexpected capabilities but not setuid" 로 거부하고 조용히 종료함 → Thunar 에서 문서를 더블클릭해도 안 열렸음.
      # (같은 원인 설명은 mods/gui/utils/media.nix 의 loupeNoCap) 실행 직전에 ambient capability 를 비움.
      makeWrapper ${pkgs.util-linux}/bin/setpriv $out/bin/onlyoffice-desktopeditors \
        --add-flags "--ambient-caps=-all ${pkgs.onlyoffice-desktopeditors}/bin/onlyoffice-desktopeditors --force-scale=${uiScale}"
      rm $out/share/applications/onlyoffice-desktopeditors.desktop
      sed "s|^Exec=[^ ]*|Exec=$out/bin/onlyoffice-desktopeditors|" \
        ${pkgs.onlyoffice-desktopeditors}/share/applications/onlyoffice-desktopeditors.desktop \
        > $out/share/applications/onlyoffice-desktopeditors.desktop
    '';
  };
in {
  os.fonts.packages = with pkgs; [
    carlito
    caladea
    liberation_ttf
    noto-fonts-cjk-sans
    noto-fonts-cjk-serif
  ];
  hm = {
    home.packages = [
      onlyoffice
      # pkgs.libreoffice-fresh # (필요하면 주석 해제: fontconfig 를 그대로 써서 폰트 문제는 없지만 OOXML 재현은 ONLYOFFICE 가 나음)
    ];

    # PDF 를 ONLYOFFICE 로 연다(래퍼의 .desktop 이라 --force-scale 이 적용됨). mimeapps.list 가 home-manager 소유라
    # Thunar 의 "기본 앱으로 설정"은 저장되지 않으므로 여기서 선언해야 한다.
    xdg.mimeApps.defaultApplications."application/pdf" = "onlyoffice-desktopeditors.desktop";

    # ONLYOFFICE 의 보조 창(닫을 때 "변경 사항을 저장하시겠습니까?" 확인창, 파일 열기/저장 창 등)은 본 창(class ONLYOFFICE)과
    # 다른 class `DesktopEditors` 의 XWayland 창이고 제목이 없음. 전역 규칙(core.ux.nix)이 모든 창을 플로팅으로 만드는데
    # 위치 지정이 없어 화면 왼쪽 위 (0,0) 에 붙었음(hyprctl clients 로 확인: at=[0,0] size=[391,112]) → 가운데로.
    wayland.windowManager.hyprland.extraConfig = ''
      hl.window_rule({ match = { class = "^(DesktopEditors)$" }, center = true })
    '';

    # ONLYOFFICE 설정(~/.config/onlyoffice/DesktopEditors.conf)은 앱이 직접 다시 쓰므로 파일 전체를 선언하지 않고
    # 필요한 키만 활성화 때 맞춘다.
    #  - UITheme: theme-dark(UI 만 어둡고 문서 용지는 흰색 유지) / theme-night(문서 배경까지 어둡게) /
    #             theme-light / theme-classic-light / theme-contrast-dark
    #  - editorWindowMode: true 면 문서를 열 때마다 새 창(앱 Settings 의 "Open file: In its own window"). false 면 한 창의 탭. true 로 두 문서가 각자 창으로 열리는 것을 확인
    #  - locale: 인터페이스 언어(ko/en 등). 앱의 Settings > Interface language 와 같은 값 (`locale=ko` 로 한국어가 되는 것을 실제로 확인)
    #  - titlebar: custom(앱이 직접 그린 둥근 창 + 최소화/닫기 버튼) / system(창 틀은 Hyprland 가 그림 → 모서리가
    #              각지고 다른 앱과 어울림. 대신 창 버튼이 없어 닫기는 단축키로)
    home.activation.onlyofficeConf = lib.hm.dag.entryAfter ["writeBoundary"] ''
      conf="$HOME/.config/onlyoffice/DesktopEditors.conf"
      if [ -z "''${DRY_RUN:-}" ]; then
        mkdir -p "$(dirname "$conf")"
        [ -f "$conf" ] || printf '[General]\n' > "$conf"
        set_key() {
          if ${pkgs.gnugrep}/bin/grep -q "^$1=" "$conf"; then
            ${pkgs.gnused}/bin/sed -i "s|^$1=.*|$1=$2|" "$conf"
          else
            ${pkgs.gnused}/bin/sed -i "/^\\[General\\]/a $1=$2" "$conf"
          fi
        }
        set_key UITheme theme-dark
        set_key titlebar system
        set_key locale ko
        set_key editorWindowMode true
      fi
    '';

    # 글꼴 힌팅(Advanced Settings > Font hinting)은 설정 파일이 아니라 앱 내부 저장소(Chromium localStorage = LevelDB)에
    # 편집기별 키 `<de|pe|sse|pdfe>-settings-fontrender` 로 들어 있음. 값: 0=as Windows(기본) / 1=as OS X / 2=Native (앱 코드로 확인).
    # 키 형식은 실제 DB 를 읽어 확인: 키 `_file://\0\x01<이름>`, 값 `\x01<문자열>`(latin1).
    # 앱이 떠 있으면 DB 가 잠겨 있어 건너뜀(다음 활성화 때 적용). DB 가 아직 없으면(새 홈) 앱을 한 번 실행한 뒤부터 적용.
    home.activation.onlyofficeFontHinting = lib.hm.dag.entryAfter ["writeBoundary"] ''
      db="$HOME/.local/share/onlyoffice/desktopeditors/data/cache/Local Storage/leveldb"
      if [ -z "''${DRY_RUN:-}" ] && [ -d "$db" ]; then
        ${pkgs.python3.withPackages (p: [p.plyvel])}/bin/python3 - "$db" 1 <<'PY' || echo "onlyoffice 글꼴 힌팅: 앱이 실행 중이라 건너뜀(종료 후 다시 활성화)"
      import sys, plyvel
      db = plyvel.DB(sys.argv[1])
      for ed in ("de", "pe", "sse", "pdfe"):
          db.put(("_file://\0\x01%s-settings-fontrender" % ed).encode("latin1"), b"\x01" + sys.argv[2].encode())
      db.close()
      PY
      fi
    '';

    home.activation.onlyofficeFonts = lib.hm.dag.entryAfter ["writeBoundary"] ''
      if [ -z "''${DRY_RUN:-}" ]; then
        mkdir -p "$HOME/.local/share/fonts"
        # 별칭 글꼴(zz-alias-*): 목록이 바뀌면 오래된 것이 남지 않게 먼저 비우고 다시 복사(변경이 없으면 내용이 같아 ONLYOFFICE 재스캔도 안 일어남)
        for old in "$HOME"/.local/share/fonts/zz-alias-*.otf; do
          [ -e "$old" ] || continue
          [ -e "${fontAliases}/$(basename "$old")" ] || rm -f "$old"
        done
        for src in ${fontAliases}/*.otf; do
          dst="$HOME/.local/share/fonts/$(basename "$src")"
          if [ -L "$dst" ] || ! ${pkgs.diffutils}/bin/cmp -s "$src" "$dst"; then
            rm -f "$dst"
            install -m 644 "$src" "$dst"
          fi
        done
        # 한글(고딕/명조) + Arial/Times New Roman/Courier New 대체(Liberation). 이름이 겹치지 않게 그대로 복사
        for src in \
          ${pkgs.nanum}/share/fonts/{NanumGothic,NanumGothicBold,NanumMyeongjo,NanumMyeongjoBold}.ttf \
          ${pkgs.liberation_ttf}/share/fonts/truetype/Liberation{Sans,Serif,Mono}-{Regular,Bold,Italic,BoldItalic}.ttf; do
          dst="$HOME/.local/share/fonts/$(basename "$src")"
          if [ -L "$dst" ] || ! ${pkgs.diffutils}/bin/cmp -s "$src" "$dst"; then
            rm -f "$dst"
            install -m 644 "$src" "$dst"
          fi
        done
      fi
    '';
  };
})
