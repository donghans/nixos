{mkModHere, ...}:
mkModHere __curPos null ({
  config,
  lib,
  ...
}: {
  hm = lib.mkIf config.mods.gui.enable {
    xdg.configFile."satty/config.toml".text = ''
      [general]
      output-filename = "~/Pictures/Screenshots/satty-%Y%m%d_%H%M%S.png"
    '';

    systemd.user.tmpfiles.rules = ["d %h/Pictures/Screenshots 0755 - - -"];
  };
})
