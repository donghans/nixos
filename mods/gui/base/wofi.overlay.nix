# Wofi Overlay: wofi 1.5.3 소스 패치 8가지(mods/_patches/wofi/*.patch, 설명은 각 패치 머리말과 README) + 시작 속도 개선(경량 커서 테마)
# 패치는 1.5.3 소스 기준 diff 라 nixpkgs 가 wofi 버전을 올리면 적용 실패(--fuzz=0)로 바로 드러남 → README 참고
# 9) (패치 아님) wofi 전용 경량 커서 테마 — GTK3 는 Wayland 의 cursor-shape 프로토콜을 지원하지 않아 시작할 때마다 커서 테마의 모든 커서를
#    직접 읽어 해석함(libwayland-cursor). Bibata-Modern-Ice 는 파일 145개(애니메이션 커서 wait/progress 는 각 9.4MB)라
#    시작 CPU 시간의 상당 부분을 차지함(perf 로 확인). 디스크 읽기가 아니라 해석 비용이라 캐시/미리 올려두기로는 줄지 않음.
#    → wofi 의 래퍼에서만 XCURSOR_PATH 를 "같은 이름의 경량 테마"(평소 쓰는 14개)로 대체함. 시스템 커서 모양은 그대로.
#    (주의: --prefix 가 아니라 --set. 시스템의 XCURSOR_PATH 에 같은 이름의 테마가 여러 곳(~/.icons, ~/.local/share, nix-profile)에
#     있어서, 앞에 붙이기만 하면 그것들까지 전부 읽혀 효과가 없었음 — 실제로 커서 파일 599개가 열림)
#    (측정: 커서 파일 열기 584 → 15개, 시작 CPU 중앙값 730 → 600ms. 나머지는 GTK3 초기화 비용)
#    (이 테마에 없는 커서가 필요한 상황은 wofi 에서 쓰는 화면(입력창, 목록)에는 없음)
_final: prev: let
  wofiCursors = prev.runCommand "wofi-light-cursors" {} ''
    src=${prev.bibata-cursors}/share/icons/Bibata-Modern-Ice
    mkdir -p $out/Bibata-Modern-Ice/cursors
    cp -L $src/index.theme $out/Bibata-Modern-Ice/ || true
    for n in default arrow left_ptr text xterm ibeam pointer hand1 hand2 grab grabbing crosshair move size_all; do
      [ -e $src/cursors/$n ] && cp -L $src/cursors/$n $out/Bibata-Modern-Ice/cursors/
    done
    test -e $out/Bibata-Modern-Ice/cursors/left_ptr
  '';
in {
  wofi = prev.wofi.overrideAttrs (old: {
    # 번호순으로 누적 적용(0004 는 0001 이 넣은 hover_select 앞에 끼워 넣음). 어긋남은 허용하지 않음
    patches =
      (old.patches or [])
      ++ [
        ../../_patches/wofi/0001-hover-select.patch
        ../../_patches/wofi/0002-focus-search-entry.patch
        ../../_patches/wofi/0003-arrow-keys-keep-entry-focus.patch
        ../../_patches/wofi/0004-placeholder-overlay.patch
        ../../_patches/wofi/0005-highlight-matches.patch
        ../../_patches/wofi/0006-fuzzy-max-len.patch
        ../../_patches/wofi/0007-surface-size-extra.patch
        ../../_patches/wofi/0008-drun-search-fields.patch
      ];
    patchFlags = (old.patchFlags or ["-p1"]) ++ ["--fuzz=0"];
    preFixup =
      (old.preFixup or "")
      + ''
        gappsWrapperArgs+=(--set XCURSOR_PATH "${wofiCursors}")
      '';
  });
}
