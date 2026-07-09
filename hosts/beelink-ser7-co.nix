{mkHostConfiguration, ...}:
mkHostConfiguration (_: {
  os = {
    # == Boot & Kernel ==
    boot = {
      kernelParams = [
        "amd_pstate=active" # (이유: 주전원 공급 시 성능 최적화)
        # [OPTIONAL] "amd_pstate=passive" (이유: USB-PD 전력 부족 시 강제 종료 방지)
      ];
    };

    # == Services & Networking ==
    # (참고: TLP 전원 관리는 mods/sys/base/os/_power.nix에서 desktop 프로파일로 자동 적용됨)
    # (참고: USB-PD 전력 부족 시 turbo 제어가 필요하면 services.tlp.settings.CPU_BOOST_ON_AC = 0 추가)
    services.irqbalance.enable = true;

    # AppImage 실행 지원 (FUSE 마운트 + binfmt 자동 실행)
    # binfmt = true: AppImage를 직접 실행 가능하게 함 (./foo.AppImage)
    # 주의: binfmt_misc는 커널 수준 공유 → Docker 컨테이너 내부에서도 적용됨.
    #   appimagetool 등 AppImage 형태의 빌드 도구가 컨테이너 안에서 실패할 수 있으므로
    #   Docker 빌드 시에는 mksquashfs + runtime-x86_64 방식으로 AppImage를 조립할 것.
    programs.appimage = {
      enable = true;
      binfmt = true;
    };
  };

  hm = {
    # (목적: 5분간 미입력 시 자동 잠금)
    services.hypridle.settings.listener = [
      {
        timeout = 300; # 5분간 미입력 시
        on-timeout = "loginctl lock-session";
      }
    ];
  };
})
