# 이미지·영상·오디오 프로그램 비교 (msi-summit-me)

이 노트북(Hyprland)에서 이미지/영상/오디오를 열 프로그램을 고르려고 시작 시간을 실측하고 특징을 정리한 기록.
**상태: 적용 완료** — 구성은 `mods/gui/utils/media.nix` (2026-10-17). 아래 "적용한 구성" 참고.

## 현재 상태 (조사 시점)

| 형식 | 기본으로 열리는 곳 |
|---|---|
| png, jpeg, gif, webp | Vivaldi (브라우저) |
| svg, avif, heic, tiff | 연결된 프로그램 없음 |
| pdf | ONLYOFFICE |
| 영상, 오디오 전부 | 연결된 프로그램 없음 |

PATH 에 뷰어/플레이어가 없고(ImageMagick `convert` 뿐), `xdg-mime query default` 가 영상/오디오에 빈 값을 돌려준다.

## 측정 방법과 조건

- 도구: `mods/_data/media-bench/bench.py` (`python3 bench.py 5`). 프로그램은 nix 로 임시 내려받고 시험 파일은 ffmpeg 로 합성한다.
- **창 시간**: 실행부터 Hyprland 에 새 창이 생길 때까지. 첫 화면/첫 소리가 나는 시점이 **아니다**.
- **CPU(2초)**: 창이 뜬 뒤 2초까지 그 프로세스 트리가 쓴 CPU 시간.
- 프로그램별 5회, 번갈아 실행, **중앙값**. 시험 파일: PNG 1080p, JPG 4K, H.264 1080p 6초(AAC), FLAC 6초.
- 조건: **AC 전원**, `intel_pstate max_perf_pct=100`, 터보 꺼짐(호스트 설정 `CPU_BOOST_ON_AC=0`), governor powersave/EPP balance_performance.
  배터리에서는 TLP 가 CPU 를 30% 로 제한해서 절대 시간이 훨씬 느리다(순위는 비슷할 것으로 보나 측정하지 않음).
- 하드웨어: Intel Iris Xe(Alder Lake-P) + NVIDIA RTX 3050 Ti Mobile, Wayland(Hyprland 0.55.2).

## 결과

| 종류 | 프로그램 | 창 | CPU(2초) |
|---|---|---:|---:|
| 이미지 PNG 1080p | swayimg | **112ms** | 320ms |
| | imv | 151ms | 180ms |
| | loupe | 1211ms | 1340ms |
| 이미지 JPG 4K | swayimg | 113ms | 440ms |
| | imv | 151ms | 210ms |
| | loupe | 1213ms | 1350ms |
| 영상 1080p H.264 | vlc | **304ms** | 780ms |
| | mpv | 522ms | 1770ms |
| | mpv + VA-API | 462ms | **900ms** |
| | celluloid | 1235ms | 3190ms |
| 오디오 FLAC | mpv (`--force-window`) | **240ms** | 330ms |
| | vlc | 277ms | 440ms |
| | amberol | 1160ms | 1320ms |
| | celluloid | 1230ms | 1530ms |

## 프로그램별 특징과 차별점

(**측정** = 위 표 / **일반** = 일반적으로 알려진 특징이며 이 시스템에서 확인하지 않음)

### 이미지

**swayimg 4.7** — Wayland 전용 뷰어.
- 한 장 보기, **갤러리(썸네일 격자)**, 슬라이드쇼를 한 프로그램에서 지원(일반). 설정 파일로 키/표시를 바꾼다(일반).
- 측정: 가장 빨리 뜸(112ms). CPU 는 imv 보다 조금 더 씀(320~440ms).
- 맞는 용도: 폴더의 사진을 훑어보는 것.

**imv 5.0.1** — 아주 작은 키보드 중심 뷰어. 타일링 창 관리자용.
- 기능이 적고 단순하며 다른 명령과 연결해 쓰기 쉬움(일반). 지원 형식은 빌드된 백엔드에 따라 다름(일반).
- 측정: 창 151ms, CPU 가 가장 적음(180~210ms).
- 맞는 용도: 파일을 가끔 한 장씩 여는 최소한의 뷰어.

**loupe 50.0** — GTK4 + libadwaita(Rust) 이미지 뷰어.
- 확대/회전/복사/이전·다음 정도의 단순한 기능, 터치패드 제스처가 자연스러움. HEIC/AVIF 같은 최신 형식 지원이 좋은 편(일반, 미확인).
- 측정: **창 1.2초, CPU 1.3초로 이미지 뷰어 중 가장 느림.**
- 맞는 용도: 시작이 느린 것을 감수하고 형식 지원/모양을 우선할 때.

### 영상

**mpv 0.41.0** — 가볍고 범용인 재생기.
- 메뉴 없는 얇은 컨트롤바(OSC), 설정 파일/스크립트로 모든 것을 조정(일반). 오디오 파일도 재생(창 없이 터미널에서 재생하는 것이 기본).
- 측정: 창 522ms. **`--hwdec=vaapi` 로 CPU 가 1770 → 900ms 로 절반**(하드웨어 디코딩이 실제로 동작함).
- 맞는 용도: 가볍고 품질 설정이 풍부한 재생, 하드웨어 디코딩으로 배터리/발열 절약.
- 주의: 처음에는 GUI 설정이 없어서 낯설다. `hwdec` 는 설정 파일에 넣어야 기본이 된다(**아직 설정하지 않음**).

**vlc 3.0.23** — 메뉴/재생목록/환경설정을 갖춘 올인원 GUI 플레이어(Qt5). Windows 에서 쓰던 것과 같은 성격.
- 이상한 형식, 스트리밍, 변환(트랜스코딩), 자막 확장 등을 폭넓게 지원(일반). 마우스로 모든 것을 하는 전통적인 UI.
- 측정: **영상에서 창이 가장 빨리 뜸(304ms)**, CPU 도 mpv(소프트웨어 디코딩)보다 적게 나옴(780ms). "VLC 는 무겁다"는 인상은 시작 시간 기준으로는 맞지 않았다.
- 주의: 이 수치는 창이 뜬 시점이라 첫 화면까지는 다를 수 있다. 첫 실행 때 메타데이터 네트워크 접근 확인창이 뜬다(측정은 `--no-metadata-network-access`).

**celluloid 0.30** — mpv 를 GTK4 창(헤더바, 재생목록, 설정 창)으로 감싼 프런트엔드.
- mpv 의 품질에 GUI 를 더한 것(일반).
- 측정: 창 1.2초, **CPU 3.2초로 영상 재생기 중 가장 무거움.** mpv 단독보다 느리고 무겁다.

### 오디오

**mpv** — 창 240ms(`--force-window`), CPU 330ms. 창 없이 터미널 재생이 기본이라 GUI 가 필요하면 부적합.
**vlc** — 창 277ms, CPU 440ms. 영상과 같은 UI 로 오디오도 처리.
**amberol 2026.1** — GTK4 의 작고 단순한 음악 재생기(대기열, 앨범 표지 등, 일반). 측정: 창 1.16초, CPU 1.3초.
**celluloid** — 창 1.2초, CPU 1.5초.
**strawberry 1.2.18** — 라이브러리 관리형 음악 재생기(Qt, 일반). **측정하지 않음.**

## 관찰한 것

- **GTK4/libadwaita 계열(loupe, celluloid, amberol)은 모두 약 1.2초**로 같은 수준이다. GTK4 가 더 빠를 것이라는 처음 추정은 틀렸다.
  렌더러를 바꿔 보아도(`GSK_RENDERER=cairo/ngl`, `GDK_DEBUG=vulkan-disable`) 1.1~1.24초로 거의 그대로여서 GPU 렌더러 초기화 때문은 아니다. 원인은 찾지 못했다.
- GTK 를 쓰지 않는 프로그램(imv, swayimg, mpv, vlc)이 빠르다. (런처 쪽도 같은 경향: fuzzel 약 0.17초 vs GTK3 wofi 약 0.6초 CPU)
- **영상 하드웨어 디코딩(VA-API)**: `intel-media-driver` 가 `environment.systemPackages` 에만 있으면 `/run/current-system/sw/lib/dri` 에 놓이는데
  libva 는 `/run/opengl-driver/lib/dri` 를 먼저 찾는다. 그래서 `vainfo` 가 실패했고, `hardware.graphics.extraPackages` 로 옮겨서 해결했다
  (`hosts/msi-summit-me.nix`). 이후 환경 변수 없이 H264/HEVC 디코딩이 잡힌다.

## 한계 (확인하지 못한 것)

- 창이 뜬 시점만 쟀다. 첫 프레임/첫 소리, 재생 중 CPU/전력, 탐색(seek) 반응은 재지 않았다.
- 배터리(CPU 30% 제한) 상태의 측정은 하지 않았다.
- 이미지 형식 지원(svg, avif, heic, tiff, jxl)과 사용성은 시험하지 않았다. "일반" 표시 항목은 일반적으로 알려진 내용이다.
- 시험 파일은 합성한 것이라 실제 사진/영화의 디코딩 부하와 다를 수 있다.

## 적용한 구성 (`mods/gui/utils/media.nix`)

| 용도 | 기본(더블클릭, 런처에서 숨김) | 직접 고르는 것(런처에 보임) |
|---|---|---|
| 이미지 | **imv-dir** | **swayimg** (Thunar 우클릭 "Open in swayimg") |
| 영상/오디오 | **mpv** (`hwdec=vaapi`) | **VLC** (Thunar 우클릭 "Open in VLC") |

실제로 확인한 것과 이유:
- **imv 는 파일 하나를 주면 그 파일만 연다**(창 제목 `[1/1]`). 폴더의 다음/이전 사진으로 넘기려면 폴더 전체를 여는 `imv-dir` 가 필요하다
  (`[2/3]` 에서 시작해 Right 로 3/3 → 1/3 순환, Left 로 되돌아옴). 그래서 기본 연결은 `imv-dir.desktop`. imv/imv-dir 는 패키지 자체가 `NoDisplay=true`.
- **swayimg 도 기본은 파일 하나만 연다**(`list.all = no`). `~/.config/swayimg/config` 에 `[list] all = yes` 를 넣으면 같은 폴더 전체를 넘긴다(옵션 없이 space 로 p2→p3 확인).
  키: Space/PageDown 다음, PageUp 이전, Ctrl+휠 확대(휠은 이동), `[`/`]` 회전, f 전체화면, Return 갤러리, s 슬라이드쇼.
  **파일 없이 켜면** 현재 폴더의 이미지를 불러오고, 이미지가 없으면 "Image list is empty" 를 남기고 바로 종료한다. 런처는 홈에서 실행되어 이미지가 없으므로
  `swayimg-open` 래퍼가 인자가 없을 때 `~/Pictures`(하위 폴더 포함, 스크린샷이 `Screenshots/` 에 있음)를 연다. swayimg 패키지의 `.desktop` 은 `NoDisplay=true` 라 같은 이름으로 다시 정의했다.
- **mpv 기본 조작**(mpv 가 알려주는 바인딩 목록으로 확인): Space/p 재생·일시정지, ←/→ 5초, ↑/↓ 60초 이동, `[`/`]` 속도, `{`/`}` 절반/두 배 속도, `9`/`0` 또는 휠 볼륨, `m` 음소거,
  `<`/`>` 이전/다음 곡, `l` A-B 반복, `L` 한 곡 반복, `f`/더블클릭 전체화면, `q` 종료. **별도의 "정지" 키는 없고 종료(q)가 정지**다(`Q` 는 위치를 저장하고 종료).
  오디오 파일도 `--player-operation-mode=pseudo-gui`(mpv.desktop 의 Exec)라서 창과 컨트롤바가 뜬다.
- mpv `hwdec=vaapi` 가 실제로 켜진다(`hwdec-current` = vaapi).
- **loupe 를 인자 없이 열면** "Open Files…" 버튼과 드래그 앤 드롭 안내가 있는 빈 창이 뜬다(파일 선택창 자체는 열어 보지 않음).
- Thunar 우클릭(`~/.config/Thunar/uca.xml` 을 선언적으로 관리 — 기존 파일은 Thunar 가 만든 "Open Terminal Here" 예제 하나뿐이라 그대로 포함): 폴더에 "Open in swayimg"/"Open in VLC"가 보이고,
  swayimg 는 폴더에서 열어 p1→p2→p3 로 넘어가는 것까지 확인했다. 이 파일은 읽기 전용 링크라 Thunar 의 "Edit > Configure custom actions" 로 고치면 저장되지 않는다(`media.nix` 를 수정).

## swayimg vs loupe (다중 파일/폴더/확대·축소) — 2026-10-17 실측

| 항목 | swayimg | loupe |
|---|---|---|
| 파일 1개 열기 | 그 파일만(`list.all=yes` 설정 시 폴더 전체) | 같은 폴더의 다음 파일로 넘어감(기본값). 끝에서 순환하지 않음 |
| 파일 여러 개 | 그 목록 | 그 목록 안에서만 이동(p1,p3 → 둘 사이) |
| 폴더 인자 | 열림(폴더 안 이미지, `recursive=yes` 면 하위 포함) | **창이 뜨지 않음**(파일+폴더 섞으면 폴더는 무시). 폴더 단위 열기는 `loupe 폴더/*` 처럼 파일로 풀어 줘야 함 |
| 인자 없이 | 현재 폴더의 이미지(없으면 종료) | "Open Files…" 버튼이 있는 빈 창 |
| 확대/축소 | `+`/`-`, Ctrl+휠, `z` 맞춤, `w`/`W` 너비/높이, `Shift+z` 채움, `BackSpace` 최적 | `+`/`-`(Ctrl 조합도), `Ctrl+0` Best Fit, `Ctrl+1` 원본 크기 |
| 이동 | 방향키·휠 | Ctrl+방향키 |
| 회전/뒤집기 | `[` `]` 회전, `m`/`Shift+m` 뒤집기 | Ctrl+R / Shift+Ctrl+R 회전 |
| 이전/다음/처음/끝 | PageUp/PageDown·Space, Home/End | ←/→, Home/End |
| 갤러리/슬라이드쇼 | 있음(Return, `s`) | 단축키 목록에 슬라이드쇼 없음, 썸네일 격자 미확인 |
| 시작 | 약 0.11초 | 약 1.2초 |

loupe 의 키는 loupe 자신의 단축키 창(F1 → Show Keyboard Shortcuts)을 화면으로 읽어 확인했다. loupe 의 터치패드 핀치/휠 확대, 마우스 드래그는 시험하지 않았다.
Thunar 의 "Open in swayimg" 는 폴더에 쓸 수 있지만 loupe 는 폴더를 못 받아서 같은 방식의 메뉴를 만들려면 `loupe "$dir"/*` 형태의 래퍼가 필요하다.

미확인:
- (확인됨) VLC 는 폴더를 열면 하위 폴더까지 재귀로 재생목록에 담는다(MPRIS 로 미디어 3개 확인, PNG 제외). 첫 실행 개인정보 대화상자는 사용자가 `qt-privacy-ask=0` 으로 꺼 둠(`~/.config/vlc`, 레포 밖 수동 설정). VLC 는 XWayland 로 뜬다.
- NoDisplay 인 imv/mpv 가 Thunar "Open With" 하위 메뉴에 보이는지(`gio mime` 목록에는 등록 앱으로 나옴). 화면 시험 중 사용자의 다른 창으로 포커스가 넘어가서 중단함.
- imv 의 HEIC/AVIF/JXL/SVG 실제 표시, 마우스 휠 확대·드래그 이동(키보드 확대는 설명서로만 확인).
- 이미지 3종(PNG만 아닌 다른 형식)·영상 기본 연결이 실제 더블클릭으로 열리는지(`xdg-mime query default` 로는 모두 연결 확인).
