{mkHostConfiguration, ...}:
mkHostConfiguration ({
  pkgs,
  lib,
  ...
}: {
  os = {
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
        "pci=nocrs" # (이유: ACPI 리소스 할당 충돌 방지 및 Firmware Bug 메시지 완화)
        "irqpoll" # (이유: 노트북 터치패드 인터럽트 충돌 방지 및 하드웨어 응답성 향상)
        "i2c_designware.disable_ps=1" # (이유: I2C 컨트롤러 절전 비활성화)
        "psmouse.synaptics_intertouch=1" # (이유: 구형 PS/2 대신 I2C/SMBus 사용 강제)
        "i8042.nopnp=1" # (이유: 구형 PS/2 포트 자동 탐색 충돌 방지)
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

    # == Services & Hardware ==
    # (목적: 부팅 시 I2C 버스 간섭 방지)
    networking.modemmanager.enable = false;
    services.fprintd.enable = false; # (이유: 지문 인식 초기화 시 프리징 방지)

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
      RUNTIME_PM_DRIVER_DENYLIST = "i2c_designware intel_ishtp intel_ishtp_hid intel_lpss_pci";
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
      touchpadToggleKey = "$mainMod CTRL, XF86TouchpadToggle";
      lidSwitchOnExtraCmd = "tlp bat";
      lidSwitchOffExtraCmd = "tlp start";
      settings = {
        monitor = lib.mkForce [
          "eDP-1,2560x1600@60,auto,1"
          "DP-2,preferred,auto-up,1"
        ];

        input.touchpad = {
          natural_scroll = true;
          tap-to-click = true;
          disable_while_typing = true;
        };
      };
    };
  };
})
