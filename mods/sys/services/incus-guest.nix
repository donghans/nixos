{
  config,
  lib,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services."incus-guest";
in {
  options.mods.sys.services."incus-guest".enable =
    mkEnableOption "Incus VM Guest (agent + SPICE vdagent)";

  config = mkIf cfg.enable (
    if isNixOS
    then {
      # (목적: incus exec 동작에 필요한 게스트 에이전트)
      # incus-agent가 실행 중이어야 호스트에서 incus exec로 VM 셸 접근 가능.
      virtualisation.incus.agent.enable = true;
      # (목적: SPICE 뷰어 ↔ VM 간 클립보드 공유)
      services.spice-vdagentd.enable = true;
    }
    else {}
  );
}
