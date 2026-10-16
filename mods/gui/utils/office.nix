# MS Office 문서(docx/xlsx/pptx) 열람·편집용 오피스 — ONLYOFFICE 와 LibreOffice 를 같이 두고 비교 중.
# (어느 쪽이 MS Office 서식을 더 잘 재현하는지 실제 문서로 확인한 뒤 하나로 정리할 것)
# 폰트: MS 전용 폰트(Calibri/Cambria 등)는 재배포할 수 없어 같은 글자 폭(metric-compatible)의 대체 폰트를 둠.
#   Calibri → Carlito, Cambria → Caladea, Arial/Times New Roman/Courier New → Liberation.
#   한글 문서는 맑은 고딕 등을 Noto CJK 로 대체하므로 글자 폭이 달라 줄바꿈 위치가 조금 달라질 수 있음.
#   (실제 MS 폰트가 필요하면 라이선스를 가진 Windows 에서 ~/.local/share/fonts 로 직접 복사)
# ONLYOFFICE 의 한글: 문서 본문은 자체 렌더링 엔진이 그리는데, 이 엔진은 시스템 폰트(fontconfig)가 아니라
#   자기가 스캔한 폰트만 씀. 스캔 대상은 번들 폰트 + /usr/share/fonts(FHS) + ~/.local/share/fonts 인데,
#   변수형 .otf.ttc(Noto CJK)와 심볼릭 링크는 건너뛰어서 한글이 □ 로 나왔음(실제 시험으로 확인).
#   → 정적 TTF(나눔, Liberation)를 ~/.local/share/fonts 에 "실제 파일"로 복사해야 하므로 home-manager 의 링크 방식 대신 활성화 때 복사.
#   LibreOffice 는 fontconfig 를 직접 써서 이 문제가 없음.
{mkModOf, ...}:
mkModOf "mods.gui" __curPos "Office (ONLYOFFICE + LibreOffice + MS 호환 폰트)" ({
  pkgs,
  lib,
  ...
}: {
  os.fonts.packages = with pkgs; [
    carlito
    caladea
    liberation_ttf
    noto-fonts-cjk-sans
    noto-fonts-cjk-serif
  ];
  hm = {
    home.packages = [
      pkgs.onlyoffice-desktopeditors
      pkgs.libreoffice-fresh
    ];

    home.activation.onlyofficeFonts = lib.hm.dag.entryAfter ["writeBoundary"] ''
      if [ -z "''${DRY_RUN:-}" ]; then
        mkdir -p "$HOME/.local/share/fonts"
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
