{
  pkgs,
  unstable,
  ...
}: let
  # (목적: UI 스케일 고정 등 환경 변수 주입 래퍼)
  wrapJetbrainsPackage = pkg: binName: (pkgs.mkWrapper {
    inherit pkg binName;
    addFlags = ["-Dsun.java2d.uiScale=1.0"];
  });
in {
  home.packages = with unstable; [
    (wrapJetbrainsPackage jetbrains.idea "idea")
    (wrapJetbrainsPackage jetbrains.datagrip "datagrip")
    (wrapJetbrainsPackage jetbrains.pycharm "pycharm")
    (wrapJetbrainsPackage jetbrains.webstorm "webstorm")
    (wrapJetbrainsPackage android-studio "android-studio")
  ];
}
