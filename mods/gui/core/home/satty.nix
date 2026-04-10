_: {
  xdg.configFile."satty/config.toml".text = ''
    [general]
    output-filename = "~/Pictures/Screenshots/satty-%Y%m%d_%H%M%S.png"
  '';

  systemd.user.tmpfiles.rules = ["d %h/Pictures/Screenshots 0755 - - -"];
}
