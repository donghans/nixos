{pkgs, ...}: {
  imports = [
    ./hardware/msi-summit-me.nix
    ./base/developer.nix
  ];

  # == Boot & Kernel ==
  # (목적: 터치패드 초기화 지연 방지 및 I2C 충돌 해결)
  boot = {
    initrd.availableKernelModules = ["i2c_hid_acpi" "intel_lpss_pci" "intel_ishtp_hid" "intel_hid" "hid_multitouch" "i2c_i801"];
    initrd.kernelModules = ["i2c_hid_acpi"];

    kernelModules = ["ec_sys"];
    kernelParams = [
      "pcie_aspm=off" # (이유: PCIe 전원 관리로 인한 끊김 방지)
      "i915.enable_psr=1"
      "pci=nocrs" # (이유: ACPI 리소스 할당 충돌 방지 및 Firmware Bug 메시지 완화)
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

  fileSystems."/boot" = {
    device = "/dev/disk/by-label/ESP";
    fsType = "vfat";
    options = ["fmask=0022" "dmask=0022"];
  };

  services.libinput.enable = true;

  # == Services & Hardware ==
  # (목적: 부팅 시 I2C 버스 간섭 방지)
  networking.modemmanager.enable = false;
  services.fprintd.enable = false; # (이유: 지문 인식 초기화 시 프리징 방지)

  services.tlp = {
    enable = true;

    settings = {
      CPU_SCALING_GOVERNOR_ON_BAT = "powersave";
      CPU_ENERGY_PERF_POLICY_ON_BAT = "power";
      CPU_MAX_PERF_ON_BAT = 50;

      CPU_SCALING_GOVERNOR_ON_AC = "balanced";
      CPU_ENERGY_PERF_POLICY_ON_AC = "balance_performance";
      CPU_MAX_PERF_ON_AC = 100;

      # (목적: 완벽한 발열 제어를 위해 AC/BAT 환경 모두 터보 부스트 강제 비활성화)
      CPU_BOOST_ON_BAT = 0;
      CPU_BOOST_ON_AC = 0;

      # (목적: 인텔 하이브리드 아키텍처 E-코어 우선 사용 유도)
      SCHED_POWERSAVE_ON_AC = 1;
      SCHED_POWERSAVE_ON_BAT = 1;

      SATA_LINKPWR_ON_BAT = "med_power_with_dipm";
      USB_AUTOSUSPEND = 0;
      USB_EXCLUDE_PHONE = 1;
      USB_DENYLIST = "04f3:2ffa"; # (이유: Elan Touchscreen 블랙리스트)

      RUNTIME_PM_ON_AC = "auto";
      RUNTIME_PM_ON_BAT = "auto";

      # (이유: 터치패드 절전 제외)
      RUNTIME_PM_DENYLIST = "00:12.0 00:15.0";
      RUNTIME_PM_DRIVER_DENYLIST = "i2c_designware intel_ishtp intel_ishtp_hid intel_lpss_pci";

      # (목적: 배터리 모드에서도 Wi-Fi 절전 비활성화)
      WIFI_PWR_ON_AC = "off";
      WIFI_PWR_ON_BAT = "off";

      DEVICES_TO_DISABLE_ON_BAT_NOT_IN_USE = "";

      MAX_LOST_WORK_SECS_ON_BAT = 60;
      MAX_LOST_WORK_SECS_ON_AC = 15;
    };
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

  # (이유: Tailscale 등 이중 NAT 환경에서 Vivaldi 동기화 타임아웃 회피)
  networking.interfaces = {
    wlo1.mtu = 1400;
  };
}
