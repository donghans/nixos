{mkMod, ...}:
mkMod __curPos "Incus VM Guest (agent + SPICE vdagent + serial console)" (_: {
  os = {
    # (목적: incus exec 동작에 필요한 게스트 에이전트)
    # incus-agent가 실행 중이어야 호스트에서 incus exec로 VM 셸 접근 가능.
    virtualisation.incus.agent.enable = true;
    # (목적: SPICE 뷰어 ↔ VM 간 클립보드 공유)
    services.spice-vdagentd.enable = true;
    # (목적: incus console 명령으로 시리얼 콘솔 접근 가능하게)
    # ttyS0 시리얼 콘솔을 활성화해야 incus console이 출력을 표시함
    boot.kernelParams = ["console=ttyS0"];
    systemd.services."serial-getty@ttyS0".enable = true;
  };
})
