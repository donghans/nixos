{mkPartOf, ...}:
mkPartOf "mods.gui" ({config, ...}: let
  # #outer-box 의 테두리/패딩 (아래 style 과 동일 값 — 바꾸면 wofi.overlay.nix 의 WOFI_EXTRA 도 extra 값으로 맞출 것)
  borderPx = 2;
  paddingPx = 9;
  extra = 2 * (borderPx + paddingPx);
in {
  hm = {
    programs.wofi.enable = true;

    programs.wofi.settings = {
      # hyprTerm은 _module.args로 전달되나 innerModule의 named arg로 받으면
      # 함수 호출 시 key set 강제평가로 순환 참조 발생 → config로 lazily 접근
      term = config._module.args.hyprTerm;
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

    # Hyprland 창 테두리(core.ui.nix: active_border #33ccff, rounding 0) 색에 맞춘 룩
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
