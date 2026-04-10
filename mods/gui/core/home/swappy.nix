_: {
  # swappy 저장 경로 및 알림 설정
  xdg.configFile."swappy/config".text = ''
    [Default]
    save_dir=$HOME/Pictures/Screenshots
    save_filename_format=swappy-%Y%m%d_%H%M%S.png
    show_notifications=true
    early_exit=true
  '';

  # Screenshots 디렉터리 생성
  systemd.user.tmpfiles.rules = ["d %h/Pictures/Screenshots 0755 - - -"];
}
