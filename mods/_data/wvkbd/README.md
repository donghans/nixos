# wvkbd 패치

`mods/gui/base/vkb.nix` 가 `pkgs.wvkbd` 에 순서대로 적용한다 (wvkbd 0.19.4 기준).

| 파일 | 내용 | 건드리는 곳 |
|---|---|---|
| `float-mode.patch` | 도킹/플로팅 모드(`--width`, `--float`, `--float-margin`, 시그널 `RTMIN+1/+2/+3`), 모드가 바뀐 뒤 훅(`--on-mode`), 새 키 종류 `Float` | `main.c`, `keyboard.c`, `keyboard.h` |
| `pc-layout.patch` | 가로 배열을 PC 표준 5줄로 교체(`Sup`·`한/영`·`⧉`·`Prt`(화면 캡처, Print 키) 포함), 세로 배열 아래줄에 `⧉`/`한/영` 추가 | `layout.mobintl.h` |

`pc-layout.patch` 는 `float-mode.patch` 가 만든 `Float` 키 종류를 쓰므로 **이 순서대로** 적용해야 한다.

## 다시 만드는 방법 (wvkbd 버전을 올려서 패치가 안 맞을 때)
```sh
S=$(nix build --no-link --print-out-paths nixpkgs#wvkbd.src)
W=$(mktemp -d); cp -r $S $W/a; cp -r $S $W/b; chmod -R u+w $W/a $W/b
patch -p1 -d $W/b < float-mode.patch        # 맞지 않는 곳만 손으로 고침
patch -p1 -d $W/b < pc-layout.patch
# ... $W/b 를 수정 ...
(cd $W && diff -ru a b) > new.patch          # 파일별로 나눠서 두 파일에 반영
```
- 패치를 나눌 때 헤더의 시각(탭 뒤)은 지워도 된다.
- 배열(`pc-layout.patch`)의 한 줄 폭 합(단위)과 줄 수는 `mods/_tools/vkb/vkb.py` 의 `LAND_UNITS`/`LAND_ROWS` 와 같아야 한다 → `mods/_tools/vkb/tests/test_vkb.py` 가 패치를 읽어 검사한다.
- 시험은 중첩이 아니라 `systemd-run --user --unit=<이름> wvkbd-mobintl ...` 로 띄워서 `grim` 으로 확인하고, 끝나면 **유닛 이름으로** 정리한다(이름으로 `pkill` 하면 실제 세션 프로세스도 죽는다).
