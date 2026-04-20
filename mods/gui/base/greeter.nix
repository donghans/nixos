{mkModOf, ...}:
mkModOf "mods.gui" __curPos "Login greeter (greetd + tuigreet)" ({
  cfg,
  pkgs,
  lib,
  ...
}: {
  options.sessionCmd = lib.mkOption {
    type = lib.types.str;
    description = "Session command passed to tuigreet --cmd (set by the window manager module)";
  };
  os = {
    services.greetd = {
      enable = true;
      settings.default_session = {
        command = "${pkgs.tuigreet}/bin/tuigreet --time --cmd '${cfg.sessionCmd}'";
        user = "greeter";
      };
    };

    systemd.services.greetd.serviceConfig = {
      Type = "idle";
      StandardInput = "tty";
      StandardOutput = "tty";
      StandardError = "journal"; # (이유: stderr는 저널로 분리하여 TTY 출력 오염 방지)
      TTYReset = true;
      TTYVHangup = true;
      TTYVTDisallocate = true;
    };
  };
})
