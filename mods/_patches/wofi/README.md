# wofi 소스 패치

`mods/gui/base/wofi.overlay.nix` 가 `patches` 로 번호순 적용한다(`patchFlags` 에 `--fuzz=0` — 어긋나면 조용히 맞추지 않고 실패).
각 패치의 이유·주의는 해당 파일 머리말에 있다.

**소스 버전 의존: wofi 1.5.3.** diff 가 1.5.3 소스의 줄 문맥에 의존하므로 nixpkgs 가 wofi 를 올리면
빌드가 패치 적용 단계에서 실패한다. 그때는 새 소스에 맞춰 패치를 다시 만든다(번호 순서대로 누적 적용해 diff 생성).

| 파일 | 대상 | 내용 |
|---|---|---|
| 0001-hover-select | src/wofi.c | 마우스 이동(motion)만으로 항목 선택 |
| 0002-focus-search-entry | src/wofi.c | 시작 시 포커스를 검색창에 둠(IME 문제) |
| 0003-arrow-keys-keep-entry-focus | src/wofi.c | 방향키는 선택만 바꾸고 포커스는 검색창 유지, Enter 는 선택 항목 실행 |
| 0004-placeholder-overlay | src/wofi.c | 포커스 중에도 보이는 플레이스홀더 라벨(0001 뒤에 적용해야 함) |
| 0005-highlight-matches | src/wofi.c | 검색 일치 글자 색+굵게 강조 |
| 0006-fuzzy-max-len | inc/match.h | 퍼지 점수 길이 한계 256 → 2048 |
| 0007-surface-size-extra | src/wofi.c | 서피스 크기에 `WOFI_EXTRA`(18) 가산 |
| 0008-drun-search-fields | modes/drun.c | drun 검색 대상을 이름+키워드+일반 이름으로 축소 |

## 주의

- **`WOFI_EXTRA`(18) 결합**: `mods/gui/base/wofi.nix` 의 `extra = 2*(borderPx+paddingPx)` 와 반드시 같아야 한다.
  값이 0007 패치에 박혀 있어 자동으로 따라가지 않으므로, wofi.nix 의 스타일 값을 바꾸면 0007 도 고친다.
- 0004 는 0001 이 추가한 `hover_select` 함수 앞에 끼워 넣는 hunk 라 순서를 바꾸면 적용되지 않는다.
- 패치 아닌 항목: 같은 오버레이의 `preFixup`(wofi 전용 경량 커서 테마, XCURSOR_PATH)은 소스를 건드리지 않는다.
- 이 패치들은 원래 오버레이의 `substituteInPlace` 문자열 치환(+`sed`)을 `diff -u` 로 기계 변환한 것이며,
  변환 전후로 패치 적용된 소스 트리가 `diff -r` 로 동일함을 확인했다.
