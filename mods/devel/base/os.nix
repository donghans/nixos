# [working-refactor] 해당 구문은 before-refactor/lib/developer.nix 에 있었음
# [working-refactor] 해당 구문은 after-refactor/... 로 들어가야 함
{config, ...}: {
  # [working-refactor] 해당 파일은 실제 /tmp/nixos-build/<경로> 로 이동 후 nhw에 의해 임시 경로에서 실행됩니다.
  imports = [
    ../../../hosts/base.dev.nix
    ../../gui/base/default.nix
  ];

  # == System Services ==
  programs.adb.enable = true;
  networking.firewall.allowedUDPPorts = [5353]; # (이유: mDNS 기반 ADB 기기 검색)

  # == User Accounts ==
  users.users.${config.workspace.username} = {
    extraGroups = ["adbusers"];
  };
}
