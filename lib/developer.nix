{metaConfig, ...}: {
  imports = [
    ../dev/base.dev.nix
    ./_base/hyprland.nix
  ];

  # == System Services ==
  services.tailscale.enable = true;

  virtualisation.docker = {
    enable = true;
    autoPrune.enable = true;
  };

  programs.adb.enable = true;
  networking.firewall.allowedUDPPorts = [5353]; # (이유: mDNS 기반 ADB 기기 검색)

  # == User Accounts ==
  users.users.${metaConfig.username} = {
    extraGroups = ["adbusers" "docker"];
  };
}
