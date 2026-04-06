{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.bluetooth;
in {
  config = mkIf (cfg.enable && isNixOS) {
    hardware.bluetooth = {
      enable = true;
      powerOnBoot = true;
    };
    services.blueman.enable = true;
  };
}
