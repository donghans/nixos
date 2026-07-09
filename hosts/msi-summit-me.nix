{mkHostConfiguration, ...}:
mkHostConfiguration ({
  pkgs,
  lib,
  ...
}: {
  os = {
    imports = [./msi-summit-me/touchpad-watchdog.nix];

    # llm-utils-project 관련 테스트를 위해 임시로 열어둔 포트
    networking.firewall.allowedTCPPorts = [7681];

    # == Clock ==
    # (목적: 듀얼부팅 시 윈도우 시간 깨짐 방지)
    # Linux는 기본적으로 하드웨어 클럭을 UTC로 다루지만, Windows는 로컬 시간으로 읽음.
    # 이 설정으로 Linux도 하드웨어 클럭을 로컬 시간으로 취급하여 양쪽 시간이 일치함.
    time.hardwareClockInLocalTime = true;

    # == Boot & Kernel ==
    # (목적: 터치패드 초기화 지연 방지 및 I2C 충돌 해결)
    boot = {
      initrd.availableKernelModules = ["i2c_hid_acpi" "intel_lpss_pci" "intel_ishtp_hid" "intel_hid" "hid_multitouch" "i2c_i801"];
      initrd.kernelModules = ["i2c_hid_acpi"];

      kernelModules = ["ec_sys"];
      kernelParams = [
        "i915.enable_psr=1"
        # pci=nocrs 제거 (2026-06-30): 의도였던 firmware-bug/리소스충돌 완화 효과가 전무했고
        #   (실재 firmware bug는 CPU토폴로지·WMI 뿐, PCI 충돌 0건), ACPI _CRS 무시 → E820 사용이
        #   오히려 LPSS I2C(00:15.0) 컨트롤러 hang(controller timed out)의 유력 원인으로 판단됨.
        "irqpoll" # (이유: 인터럽트 스톰/누락 IRQ를 폴링으로 정리 — 제거 시 발열·배터리소모 악화 체감하여 유지)
        # 정리(2026-06-30): 아래 두 파라미터 제거.
        #   - psmouse.synaptics_intertouch=1 : psmouse 모듈을 blacklist 했고 터치패드는 i2c_hid_acpi라 무효(no-op)
        #   - i8042.nopnp=1 : i8042는 터치패드(I2C)가 아닌 내장 키보드용 — 터치패드 문제와 무관
        # 참고: i2c_designware.disable_ps=1 은 kernel 6.18+ 에서 모듈이 없어 무효 → udev 룰로 대체
      ];

      blacklistedKernelModules = [
        "nouveau"
        "nvidia"
        "nvidia_drm"
        "nvidia_modeset"
        "psmouse" # (이유: 최신 I2C 터치패드와 충돌하는 구형 드라이버 차단)
      ];
      extraModprobeConfig = ''
        blacklist nouveau
        options nouveau modeset=0
        options ec_sys write_support=1
      '';
    };

    services.libinput.enable = true;

    # (이유: TLP RUNTIME_PM_DENYLIST는 TLP 서비스 시작 후 적용되어 부팅 초기 probe 시점엔 늦음.
    #  kernel 6.18+ 에서 i2c_designware 모듈이 없어 disable_ps 파라미터도 무효가 됨.
    #  I2C 컨트롤러(0x51e8)가 runtime suspend 상태로 터치패드 probe 실패 방지를 위해
    #  udev add 타이밍에 직접 power/control=on 강제.)
    #
    # (이유: idma64.0과 i2c_designware.0이 IRQ 27을 공유하는데, DMA 모드에서 spurious interrupt가
    #  발생하면 irqpoll 없이는 발열/배터리 문제, irqpoll 있으면 I2C 상태머신 타이밍 어긋남 →
    #  "controller timed out" storm. idma64.0을 언바인드해 i2c_designware를 PIO 모드로 강제하면
    #  IRQ 27 단독 소유 → 두 문제 동시 해결 기대.)
    services.udev.extraRules = ''
      ACTION=="add", SUBSYSTEM=="pci", ATTR{vendor}=="0x8086", ATTR{device}=="0x51e8", ATTR{power/control}="on"
      ACTION=="bind", SUBSYSTEM=="platform", KERNEL=="idma64.0", RUN+="${pkgs.bash}/bin/sh -c 'echo idma64.0 > /sys/bus/platform/drivers/idma64/unbind'"
    '';

    # == Services & Hardware ==
    # (목적: 부팅 시 I2C 버스 간섭 방지)
    networking.modemmanager.enable = false;
    services.fprintd.enable = true; # (Goodix 27c6:6094 MOC 지문 센서 — libfprint goodixmoc 드라이버로 동작 확인됨)

    # (참고: TLP 기본 laptop 프로파일은 mods/sys/base/os/_power.nix에서 적용됨)
    # MSI 전용 TLP quirk 추가 설정
    services.tlp.settings = {
      # (목적: MSI Summit E13 발열 제어 — AC 어댑터 전력 한계로 터보 강제 비활성화)
      CPU_BOOST_ON_AC = 0;
      CPU_BOOST_ON_BAT = 0;

      # (목적: Intel 하이브리드 아키텍처 E-코어 우선 사용 유도)
      SCHED_POWERSAVE_ON_AC = 1;
      SCHED_POWERSAVE_ON_BAT = 1;

      # (이유: Elan Touchscreen USB 절전 제외)
      USB_DENYLIST = "04f3:2ffa";

      # (이유: I2C 터치패드 디바이스 런타임 절전 제외)
      RUNTIME_PM_DENYLIST = "00:12.0 00:15.0";
      RUNTIME_PM_DRIVER_DENYLIST = "intel-lpss intel_ishtp intel_ishtp_hid";
    };

    # == Power Management & Interfaces ==
    services.logind.settings.Login = {
      # (목적: 덮개를 닫았을 때 절전 방지)
      HandleLidSwitch = "ignore";
      HandleLidSwitchExternalPower = "ignore";
      HandleLidSwitchDocked = "ignore";
      IdleAction = "ignore";
    };

    # (목적: Wi-Fi 네트워크 절전 방지)
    networking.networkmanager.wifi.powersave = false;

    programs.appimage = {
      enable = true;
      binfmt = true;
    };

    environment.systemPackages = with pkgs; [
      intel-media-driver
      libva-vdpau-driver
      libvdpau-va-gl

      # == MSI Special Hardware Controls ==
      (writeShellScriptBin "turbo-on" ''
        echo -en '\x80' | sudo dd of="/sys/kernel/debug/ec/ec0/io" bs=1 seek=152 count=1 conv=notrunc 2>/dev/null
      '')
      (writeShellScriptBin "turbo-off" ''
        echo -en '\x04' | sudo dd of="/sys/kernel/debug/ec/ec0/io" bs=1 seek=152 count=1 conv=notrunc 2>/dev/null
      '')
    ];
  };

  hm = {
    wayland.windowManager.hyprland = {
      touchpadToggleKey = "SUPER + CTRL, F24";
      lidSwitchOnExtraCmd = "tlp bat";
      lidSwitchOffExtraCmd = "tlp start";
      settings = {
        monitor = lib.mkForce [
          "eDP-1,2560x1600@60,auto,1"
          ",preferred,auto-up,1"
        ];

        input.touchpad = {
          natural_scroll = true;
          tap_to_click = true;
          disable_while_typing = true;
        };
      };
    };
  };
})
