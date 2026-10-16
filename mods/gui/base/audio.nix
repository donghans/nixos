# 오디오 조작 UI.
# - pasystray: 트레이 아이콘(음량 표시, 스크롤=음량, 가운데 클릭=음소거). 클릭하면 Default Sink/Source 로
#   출력·입력 장치를 바꾸고 앱별 스트림을 옮길 수 있음. 트레이는 ayatana-appindicator(StatusNotifierItem)로
#   waybar 트레이에 표시됨. (시작 로그의 Avahi 오류는 네트워크 오디오 탐색 데몬이 없다는 것이라 무시해도 됨)
# - pavucontrol: 상세 설정(장치/포트/앱별 음량). pasystray 메뉴의 "Volume Control…" 로 열림
# - 단축키(볼륨/음소거/마이크 음소거)는 core.bind.hwctl.nix 의 vol-control
{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  pkgs,
  lib,
  ...
}: {
  hm = {
    home.packages = [
      pkgs.pasystray
      pkgs.pavucontrol
    ];

    # waybar(900, 시작 2초 지연) 뒤에 시작해 트레이에 등록
    wayland.windowManager.hyprland.settings.exec-once = lib.mkOrder 950 [
      "uwsm app -- ${pkgs.pasystray}/bin/pasystray"
    ];
  };
})
