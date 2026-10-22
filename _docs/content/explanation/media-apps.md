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
| 이미지 | **imv-dir** | **loupe** (Thunar 우클릭 "Open in Loupe") — 2026-10-17 swayimg 에서 교체 |
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

### swayimg → loupe 교체 (2026-10-17)
- 이유: loupe 에는 **편집**이 있다(헤더의 자르기 버튼 → 비율 Free/Original/Square/5:4/4:3/3:2/16:9, 회전, 좌우·상하 뒤집기, Save 드롭다운). swayimg/imv 에는 자르기·저장이 없다(swayimg 는 `exec` 바인딩으로 외부 명령 연결만, 키 목록 확인). 슬라이드쇼는 필요 없다고 판단.
- 아쉬운 점 해결: loupe 는 폴더를 인자로 받으면 창이 안 뜬다 → `loupe-open` 래퍼(`media.nix`)가 폴더를 안의 이미지 파일 목록(이름순, 하위 폴더 제외)으로 풀어서 넘김.
  Thunar 폴더 우클릭 "Open in Loupe" 로 `p1→p2→p3` 넘기기 확인. 이미지가 없는 폴더는 빈 창이 뜸. loupe 명령줄 옵션은 사실상 없음(`--help` 에 GApplication 옵션뿐).
  loupe 의 "Open Files…" 선택창에서 Ctrl+A 로 폴더 전체를 고르는 방법도 있을 것으로 보나 시험하지 않음.
- swayimg 는 제거(패키지/설정/런처 항목). 필요하면 git 이력(`0186aa8`)에서 복원.

### loupe "Could not Load Image" — Hyprland 가 물려준 CAP_SYS_NICE (2026-10-17)
- 증상: Thunar 우클릭/런처에서 연 loupe 만 정상 JPEG(`Downloads/20260905_142232.jpg`, Galaxy S25 사진)를 "Could not Load Image" 로 못 염. **같은 파일이 터미널(내 셸)·`systemd-run --user` 로는 열림.**
  상세 메시지: `Loader process exited early with status '1'` + bubblewrap(`bwrap --unshare-all …`) 명령.
- 원인: loupe 의 이미지 로더(glycin)는 bwrap 샌드박스에서 도는데, **bwrap 은 setuid 가 아니면서 capability 를 가진 채로는 "Unexpected capabilities but not setuid" 로 거부하고 종료 코드 1**.
  NixOS 의 Hyprland 래퍼가 `cap_setpcap,cap_sys_nice=ep` 이고(`getcap /run/wrappers/bin/*`), Hyprland 프로세스와 그 자식들(Thunar 데몬 `.thunar-wrapped`, waybar 등)이
  `CapAmb: 0000000000800000`(= CAP_SYS_NICE ambient)을 가짐(`/proc/<pid>/status`). 권한이 없는 경로(내 셸 `CapEff: 0`)에서는 정상. 같은 이유로 Hyprland 세션에서 뜬 glycin 기반 앱은 모두 영향을 받을 수 있음.
- 해결(`mods/gui/utils/media.nix`): PATH 의 `loupe` 를 `setpriv --ambient-caps=-all <loupe>` 래퍼(`lib.hiPrio`)로 가림 → exec 후 권한이 사라짐. `loupe-open` 도 이 래퍼를 씀.
  검증: Thunar 우클릭 "Open in Loupe" 로 같은 파일이 열리고 그 프로세스의 `CapAmb` 가 0 으로 바뀜(수정 전에는 `800000`, 실패).
- 참고: loupe 는 단일 인스턴스라 이미 실패 상태로 떠 있는 loupe 가 있으면 새로 열어도 그 프로세스로 전달되어 계속 실패함 → 그 창을 모두 닫아야 함(수정 전 증상 분석 중 이로 인해 혼동).
- 미확인: 런처(wofi)·"Open With" 경로는 `loupe` 를 PATH 에서 찾으므로 같은 래퍼를 쓸 것으로 보나 직접 시험하지 않음.

### ONLYOFFICE 대체 글꼴 (2026-10-17)
- 문서가 지정한 글꼴이 설치돼 있지 않으면 ONLYOFFICE 가 **스캔한 글꼴(`~/.local/share/fonts` 등) 중에서 자체 알고리즘으로** 대체 글꼴을 고른다(fontconfig 와 무관, 대체 규칙을 지정하는 설정은 못 찾음).
  실제 pptx(`Ⅴ. 프로젝트 관리_v0.93 (1).pptx`)에서 눈으로 대조한 결과 `에스코어 드림 6 Bold`(고딕) 제목은 **바탕체 계열**로, `KoPub돋움체` 본문은 가는 굴림/돋움 계열로 그려졌음(확정은 아님).
  이 문서가 쓰는데 없는 글꼴: KoPub돋움체/바탕체, 에스코어 드림 5·6·7, 산돌고딕B. nixpkgs 에도 없음.
- **해결**: 없는 이름과 같은 이름의 글꼴을 Pretendard(`pkgs.pretendard`, 굵기별 정적 OTF)에서 만들어 둠. 이름표(name 테이블)만 바꾼 복사본이고 글리프는 Pretendard 그대로.
  `mods/_data/office-fonts/alias.py` + `office.nix` 의 `fontAliasMap`(이름 → Pretendard 굵기). 활성화 때 `~/.local/share/fonts/zz-alias-*.otf` 로 실제 파일 복사(ONLYOFFICE 가 심볼릭 링크를 건너뜀).
  검증: 별칭을 넣고 ONLYOFFICE 를 **완전히 재시작**하자 `fonts.log` 가 재스캔되고, 제목이 바탕체에서 굵은 고딕(Pretendard Bold)으로, 본문이 Pretendard 로 바뀜.
- 주의: (1) ONLYOFFICE 는 프로필 경로와 무관하게 **프로세스가 하나뿐**이고 글꼴 목록은 시작할 때 한 번만 읽으므로 새 글꼴은 완전 종료 후 다시 켜야 보임(독립 인스턴스로 시험 불가).
  (2) 모양은 Pretendard 이지 원래 KoPub/에스코어 드림이 아님 → 글자 폭이 달라 줄바꿈 위치가 조금 다를 수 있음. (3) `KoPub바탕체`(명조)는 별칭을 만들지 않아 지금도 ONLYOFFICE 기본 대체(바탕 계열).
  (4) 다른 문서에서 대체되는 이름이 생기면 `fontAliasMap` 에 한 줄 추가. (5) 이름표를 바꾼 복사본이므로 개인용으로만 둘 것.
- fontTools 로 Mac 이름표(`platformID 1`)에 한글을 넣으면 Mac Roman 인코딩 오류로 저장이 실패함 → Windows 이름표만 사용.

### ONLYOFFICE 글꼴 뻣뻣함 · 언어 · 확인창 위치 (2026-10-17)
- **글꼴이 뻣뻣한 원인**: 시스템 fontconfig/FreeType 이 아니라 ONLYOFFICE 자체 엔진(FreeType 이 `fonts.wasm` 에 내장, 시스템 것을 안 씀)의 힌팅.
  시스템 설정은 NixOS 기본(`hintstyle slight`, 회색조, 서브픽셀 없음)인데 ONLYOFFICE 는 pango 의 medium/full 힌팅과 비슷한 수치(회색 22%/진한 검정 64% vs 20%/68%; slight 는 36%/33%)였음.
  세 개 중 선택지: `as Windows`(기본) / `as OS X` / `Native`. **`as OS X` 로 바꾸니 획이 부드러워지고 간격이 자연스러워짐**(사용자도 확인). `Native` 는 시험하지 않음.
- **설정 위치**: 문서를 연 뒤 `File` → 왼쪽 패널 **맨 아래** `Advanced Settings` → `Font hinting` → 선택 후 **`Apply`**. 이 값은 설정 파일(`DesktopEditors.conf`)이 아니라 앱 내부 저장소(Chromium localStorage, LevelDB: `Local Storage/leveldb`)의 편집기별 키 `<de|pe|sse|pdfe>-settings-fontrender` 에 들어감. 값은 `0`=as Windows / `1`=as OS X / `2`=Native(앱 `code.js` 로 확인). 키 `_file://\0\x01<이름>`, 값 `\x01<문자열>`.
  → `office.nix` 의 `onlyofficeFontHinting` 활성화가 plyvel 로 네 키를 `1` 로 맞춤(2026-10-22). 앱이 떠 있으면 DB 잠금으로 건너뛰고, DB 가 아직 없는 새 홈은 앱을 한 번 실행한 뒤부터 적용.
  검증은 복사본 DB 에 쓰고 읽어 형식을 확인한 것까지이고, 활성화 시점에는 이미 값이 `1` 이라 실제로 바뀌는 경로는 확인하지 못함.
  (자동 조작 시 주의: 드롭다운 항목은 커서를 순간이동만 시키면 호버가 없어 안 눌리므로 실제 이동 이벤트를 준 뒤 클릭해야 함.)
- **인터페이스 언어**: `DesktopEditors.conf` 의 `locale=ko` 로 한국어가 됨(실제 확인: 메뉴·설정·저장 확인창 모두 한국어). `office.nix` 의 활성화 스크립트가 이 키를 맞춤.
  처음에 "설정 파일로는 안 된다"고 한 것은 확인 없이 한 말이라 틀렸음. Region/Formula language 는 Advanced Settings 쪽이라 별개(현재 English).
- **저장 확인창이 왼쪽 위에 뜨던 문제**: 확인창은 본 창(class `ONLYOFFICE`)과 다른 class `DesktopEditors` 의 제목 없는 XWayland 창이고, 전역 규칙(`core.ux.nix`, 모든 창 플로팅)에는 위치 지정이 없어 `(0,0)` 에 붙음.
  `hl.window_rule({ match = { class = "^(DesktopEditors)$" }, center = true })` 를 `office.nix` 에 추가. 검증: 확인창이 `(1085,756)` 에 뜸(2560x1600 모니터의 중앙은 `(1085,744)`).
  같은 class 의 다른 보조 창(파일 열기/저장 등)에도 적용되나 직접 확인하지는 않음.

### ONLYOFFICE 도 같은 원인으로 Thunar 에서 안 열림 (2026-10-17)
- 증상: Thunar 에서 PDF 더블클릭/우클릭 "Open With ONLYOFFICE" 를 해도 아무 창도 안 뜨고 오류도 없음(프로세스·저널 흔적 없음). 터미널이나 `hyprctl dispatch exec` 로 같은 명령을 실행하면 정상.
- 원인: loupe 와 동일. ONLYOFFICE 는 `buildFHSEnv`(bubblewrap)이라 Thunar 데몬이 물려받은 ambient CAP_SYS_NICE 가 있으면 bwrap 이 거부하고 조용히 종료.
- 해결(`mods/gui/utils/office.nix`): 실행 래퍼를 `setpriv --ambient-caps=-all <onlyoffice>` 로 바꿈. 검증: Thunar 우클릭 "Open With ONLYOFFICE" 로 PDF 가 열리고 프로세스의 `CapAmb` 가 0.
- 그 전에 사용자가 쓰던 ONLYOFFICE 인스턴스가 떠 있었던 것은 다른 경로(런처)로 실행됐기 때문으로 보이나, 경로별 권한 차이의 정확한 이유는 확인하지 못함(`hyprctl dispatch exec` 로 띄운 프로세스는 `CapAmb` 0 이었는데 Thunar 데몬 자식은 `800000`).

### 메모(주석) — satty
- loupe 의 편집은 자르기/회전/뒤집기뿐이고 그리기·글자·화살표 같은 메모 도구는 없다(화면으로 확인).
- satty 는 `--filename <파일>` 로 **기존 이미지 파일도 열 수** 있다(스크린샷 단축키가 쓰는 `--filename -` 는 stdin). 도구: 자르기, 펜, 선, 화살표, 사각형, 원, 글자, 번호, 블러, 형광펜.
  satty 자체 `.desktop` 은 `NoDisplay=true`, MimeType 은 PNG/JPEG 뿐이라 런처에는 안 나옴. 다른 형식(WebP 등)과 저장 동작은 시험하지 않음.
- Thunar 이미지 우클릭 "Annotate with Satty" (`satty --filename %f`, 공백 있는 경로도 열림 확인). 저장은 `mods/gui/base/satty.nix` 의 `output-filename`
  (`~/Pictures/Screenshots/satty-날짜시각.png`)이라 **원본은 그대로 두고 새 파일로 저장**된다.

### mpv 이전/다음
- 기본은 파일 하나를 열면 재생목록도 하나라 `<`/`>` 가 안 먹는다. 여러 파일을 선택해 열면 그 목록이 재생목록(한 창에서 순서대로).
- `autocreate-playlist=same` 을 켜서 해결: `b.flac` 을 열면 `[a.mp3, b.flac, c.mp3]`(오디오끼리), `d.mp4` 는 영상끼리(해당 폴더에 영상이 하나면 그것뿐). `filter` 는 PNG 까지 섞여서 `same` 선택.
- 따라서 imv 를 "한 개만 열기"로 맞출 이유가 없어 **imv-dir(폴더 순환) 유지**. (한 개만 열기를 원하면 기본 연결을 `imv.desktop` 으로 바꾸면 됨: 파일 하나=그 파일만, 여러 개 선택=그 목록)

미확인:
- (확인됨) VLC 는 폴더를 열면 하위 폴더까지 재귀로 재생목록에 담는다(MPRIS 로 미디어 3개 확인, PNG 제외). 첫 실행 개인정보 대화상자는 사용자가 `qt-privacy-ask=0` 으로 꺼 둠(`~/.config/vlc`, 레포 밖 수동 설정). VLC 는 XWayland 로 뜬다.
- NoDisplay 인 imv/mpv 가 Thunar "Open With" 하위 메뉴에 보이는지(`gio mime` 목록에는 등록 앱으로 나옴). 화면 시험 중 사용자의 다른 창으로 포커스가 넘어가서 중단함.
- imv 의 HEIC/AVIF/JXL/SVG 실제 표시, 마우스 휠 확대·드래그 이동(키보드 확대는 설명서로만 확인).
- 이미지 3종(PNG만 아닌 다른 형식)·영상 기본 연결이 실제 더블클릭으로 열리는지(`xdg-mime query default` 로는 모두 연결 확인).
