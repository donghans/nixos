{mkPartOf, ...}:
mkPartOf "mods.sys.base" (_: {
  os = {
    # == 수동 백그라운드 작업용 저우선순위 슬라이스 (유저 매니저) ==
    # (목적: 터미널에서 직접 돌리는 대용량 다운로드/수동 컴파일/스트레스 테스트 등을
    #        opt-in으로 던져넣는 슬라이스. `bgrun <cmd>`로 사용 (zsh init.zsh 참고))
    # (참고: background.slice는 systemd 기본 제공 유저 슬라이스 — CPUWeight=30만 기본 설정되어
    #        있어 IOWeight/MemoryHigh를 추가로 낮춰줌. session.slice(=Hyprland 등 전체 그래픽
    #        세션)와 완전히 분리된 cgroup이라 데스크탑 반응성에 직접 영향을 주지 않음)
    systemd.user.slices."background.slice".sliceConfig = {
      CPUWeight = 20;
      IOWeight = 20;
      MemoryHigh = "50%";
    };
  };
})
