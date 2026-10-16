# 오디오 조작 UI.
# - pasystray: 트레이 아이콘(자동 시작은 패키지의 XDG autostart)(음량 표시, 스크롤=음량, 가운데 클릭=음소거). 클릭하면 Default Sink/Source 로
#   출력·입력 장치를 바꾸고 앱별 스트림을 옮길 수 있음. 트레이는 ayatana-appindicator(StatusNotifierItem)로
#   waybar 트레이에 표시됨. (시작 로그의 Avahi 오류는 네트워크 오디오 탐색 데몬이 없다는 것이라 무시해도 됨)
# - pavucontrol: 상세 설정(장치/포트/앱별 음량). pasystray 메뉴의 "Volume Control…" 로 열림
# - 단축키(볼륨/음소거/마이크 음소거)는 core.bind.hwctl.nix 의 vol-control
{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  pkgs,
  ...
}: {
  hm = {
    home.packages = [
      pkgs.pasystray
      pkgs.pavucontrol
    ];

    # (pasystray 는 패키지가 XDG 자동 시작(app-pasystray@autostart.service)을 제공해서 로그인 때 저절로 뜸.
    #  exec-once 로 한 번 더 띄우면 트레이 아이콘이 둘이 되므로 별도로 시작하지 않음)
  };
})
