{mkPartOf, ...}:
mkPartOf "mods.gui" ({config, ...}: let
  # #outer-box 의 테두리/패딩 (아래 style 과 동일 값 — 바꾸면 wofi.overlay.nix 의 WOFI_EXTRA 도 extra 값으로 맞출 것)
  # (테두리는 일반 창 모드에서 Hyprland 가 직접 그리므로 CSS 테두리는 0)
  borderPx = 0;
  paddingPx = 9;
  extra = 2 * (borderPx + paddingPx);
in {
  hm = {
    programs.wofi.enable = true;

    # 일반 창 모드 wofi: 모든 창이 기본 플로팅(core.ux.nix)이므로 위치만 지정
    wayland.windowManager.hyprland.extraConfig = ''
      hl.window_rule({
        match = { class = "^(wofi)$" },
        center = true
      })
    '';

    programs.wofi.settings = {
      # hyprTerm은 _module.args로 전달되나 innerModule의 named arg로 받으면
      # 함수 호출 시 key set 강제평가로 순환 참조 발생 → config로 lazily 접근
      term = config._module.args.hyprTerm;
      # (목적: 레이어 서피스 대신 일반 창(xdg_toplevel)으로 띄움)
      # (이유: 레이어 서피스는 fcitx5 가 자체 입력 컨텍스트를 만들지 못하고 직전 앱의 컨텍스트(한/영 상태)를 공유함.
      #        일반 창이면 별도 컨텍스트라 다른 앱처럼 영어로 시작하고, 이전 앱의 한/영 상태도 건드리지 않음.
      #        Hyprland 의 활성/비활성 테두리·투명도·마우스 포커스 규칙도 일반 창처럼 적용됨)
      normal_window = true;
      # (이유: wofi 는 width/height 로 레이어 서피스 크기를 요청하는데, CSS 의 테두리+패딩(양쪽 합 extra px)이
      #        창을 더 크게 만들어 요청 크기와 어긋나면 입력/포커스마다 크기 재협상으로 흔들림 → extra 만큼 보정)
      # (이유: lines 를 쓰면 입력/포커스 변화마다 창 높이를 재계산하므로 고정 px 사용)
      width = 700 - extra;
      height = 620 - extra;
      prompt = "검색";
      # (목적: fuzzel 처럼 클릭 한 번으로 실행 — hover 선택은 wofi.overlay.nix 패치)
      single_click = true;
      allow_images = true;
      image_size = 24;
      insensitive = true;
      no_actions = true;
    };

    # 일반 창 모드라 테두리/투명도는 Hyprland 창 규칙(core.ui.nix: active_border #33ccff, rounding 0)이 적용됨
    # 배경 검정, 선택 #268bd2 는 fuzzel 시절 색상 유지
    programs.wofi.style = ''
      * {
        border-radius: 0px;
      }
      #window {
        margin: 0px;
        border: none;
        background-color: #000000;
        font-family: "NanumGothicCoding";
        font-size: 13px;
      }
      #input {
        margin: 0px 0px 6px 0px;
        padding: 3px 10px;
        border: none;
        box-shadow: none;
        outline: none;
        color: #ffffff;
        background-color: #000000;
      }
      #outer-box {
        margin: 0px;
        padding: ${toString paddingPx}px;
        border: ${toString borderPx}px solid #33ccff;
        background-color: #000000;
      }
      #inner-box, #scroll {
        margin: 0px;
        padding: 0px;
        border: none;
        background-color: #000000;
      }
      /* 플레이스홀더(wofi.overlay.nix 의 겹침 라벨): 돋보기 아이콘 오른쪽에 정렬 */
      #placeholder {
        margin-left: 32px;
        /* 세로 가운데 정렬이 입력 글자보다 3px 아래라 아래 여백으로 3px 올림 (실측) */
        margin-bottom: 6px;
        color: #7a7a7a;
      }
      #entry {
        margin: 0px;
        padding: 2px 10px;
      }
      #text {
        margin: 0px 8px;
        color: #ffffff;
      }
      #entry:selected {
        background-color: #268bd2;
      }
      #entry:selected #text {
        color: #ffffff;
      }
    '';
  };
})
