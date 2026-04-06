_: {
  # (목적: 5분간 미입력 시 자동 잠금)
  services.hypridle.settings.listener = [
    {
      timeout = 300; # 5분간 미입력 시
      on-timeout = "loginctl lock-session";
    }
  ];

  # == 프리셋: 워크스테이션 전체 도메인 활성화 ==
  mods._preset.workstation.enable = true;

  # == 호스트별 앱 선택 ==
  mods.gui.apps.vivaldi.enable = true;
  mods.gui.apps.slack.enable = true;
  mods.gui.apps.bitwarden.enable = true;
  mods.gui.utils.notifications_logger.enable = true;
  mods.devel.jetbrains.android-studio.enable = true;
}
