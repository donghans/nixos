# == 워크스테이션 프리셋 ==
# 개발자 워크스테이션을 위한 표준 구성 레시피.
# sys+gui+devel 전체 도메인을 일괄 활성화한다.
# 호스트별 앱 선택(vivaldi, slack, android-studio 등)은 각 호스트에서 명시적으로 선택한다.
{
  lib,
  config,
  ...
}:
with lib; let
  cfg = config.mods._preset.workstation;
in {
  config = mkMerge [
    {
      # == Strict Governance: 명시적 opt-in 강제 ==
      # mods.gui.enable 또는 mods.devel.enable이 활성화되려면 반드시 이 프리셋을 사용해야 한다.
      # 미선언 도메인 활성화를 방지하여 설정 드리프트를 빌드 타임에 차단한다.
      assertions = [
        {
          assertion = config.mods.gui.enable -> cfg.enable;
          message = ''
            [Strict Governance] mods.gui.enable = true 를 사용하려면
            mods._preset.workstation.enable = true 가 필요합니다.
            프리셋 없이 수동으로 도메인을 활성화하는 것은 허용되지 않습니다.
          '';
        }
        {
          assertion = config.mods.devel.enable -> cfg.enable;
          message = ''
            [Strict Governance] mods.devel.enable = true 를 사용하려면
            mods._preset.workstation.enable = true 가 필요합니다.
            프리셋 없이 수동으로 도메인을 활성화하는 것은 허용되지 않습니다.
          '';
        }
      ];
    }

    (mkIf cfg.enable {
      # == Tier 1: 시스템 기반 ==
      mods.sys.base.enable = true;
      mods.sys.utils.nfd.enable = true;

      # == Tier 2: 서비스 ==
      mods.sys.services.bluetooth.enable = true;
      mods.sys.services.networkmanager.enable = true;
      mods.sys.services.tailscale.enable = true;
      mods.sys.services.docker.enable = true;

      # == Tier 3: GUI ==
      mods.gui.enable = true;

      # == Tier 4: 개발 도구 ==
      mods.devel.enable = true;
    })
  ];
}
