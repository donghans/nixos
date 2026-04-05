{...}: {
  imports = [../../lib/developer.home.nix];

  # (목적: 5분간 미입력 시 자동 잠금)
  services.hypridle.settings.listener = [
    {
      timeout = 300; # 5분간 미입력 시
      on-timeout = "loginctl lock-session";
    }
  ];
}
