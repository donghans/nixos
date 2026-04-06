import os

def write_mod(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)

# 1. sys/fonts.nix
write_mod('mods/sys/fonts.nix', '''{ config, lib, pkgs, ... }:
with lib;
let cfg = config.mods.sys.fonts;
in {
  config = mkIf cfg.enable {
    fonts = {
      packages = with pkgs; [
        nanum
        nanum-gothic-coding
        noto-fonts-cjk-sans
        noto-fonts-cjk-serif
        noto-fonts-color-emoji
      ];
      fontconfig.defaultFonts = {
        serif = ["NanumMyeongjo" "Noto Serif CJK KR"];
        sansSerif = ["NanumGothic" "Noto Sans CJK KR"];
        monospace = ["NanumGothicCoding"];
        emoji = ["Noto Color Emoji"];
      };
    };
  };
}''')

# 2. sys/vfs.nix
write_mod('mods/sys/vfs.nix', '''{ config, lib, pkgs, isNixOS ? false, ... }:
with lib;
let cfg = config.mods.sys.vfs;
in {
  config = mkIf cfg.enable (mkMerge [
    (mkIf isNixOS {
      services.gvfs.enable = true;
      services.udisks2.enable = true;
    })
    (mkIf (!isNixOS) {
      home.packages = with pkgs; [ trash-cli ];
      # aliases could be moved here if they exist
    })
  ]);
}''')

# 3. sys/services/bluetooth.nix
write_mod('mods/sys/services/bluetooth.nix', '''{ config, lib, ... }:
with lib;
let cfg = config.mods.sys.services.bluetooth;
in {
  config = mkIf cfg.enable {
    hardware.bluetooth = {
      enable = true;
      powerOnBoot = true;
    };
    services.blueman.enable = true;
  };
}''')

# 4. sys/services/tailscale.nix
write_mod('mods/sys/services/tailscale.nix', '''{ config, lib, ... }:
with lib;
let cfg = config.mods.sys.services.tailscale;
in {
  config = mkIf cfg.enable {
    services.tailscale.enable = true;
  };
}''')

# 5. sys/services/docker.nix
write_mod('mods/sys/services/docker.nix', '''{ config, lib, ... }:
with lib;
let cfg = config.mods.sys.services.docker;
in {
  config = mkIf cfg.enable {
    virtualisation.docker = {
      enable = true;
      autoPrune.enable = true;
    };
    users.users.${config.workspace.username}.extraGroups = [ "docker" ];
  };
}''')

# 6. sys/utils/nfd.nix
write_mod('mods/sys/utils/nfd.nix', '''{ config, lib, ... }:
with lib;
let cfg = config.mods.sys.utils.nfd;
    isNixOS = config ? system; # rough check, or use isNixOS arg if passed
in {
  config = mkIf cfg.enable {
    # Assuming nfd logic will be imported or defined here
    # We will just import the existing nfd module wrapped in mkIf
  };
}''')

print("Scaffolded sys modules.")
