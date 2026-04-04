{
  pkgs,
  unstable,
  lib,
  metaConfig,
  ...
}: {
  imports = [./base/developer.home.nix];

  # 시간이 흘렀을 때 자동 잠금
  services.hypridle.settings.listener = [
    {
      timeout = 300; # 5분간 미입력 시
      on-timeout = "loginctl lock-session";
    }
  ];
}
