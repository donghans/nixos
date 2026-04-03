{ config, pkgs, ... }: {
  imports = [
    ./hardware/msi-summit-me.nix
    ./base/developer.nix
  ];

  # 터치패드 초기화 지연 해결을 위한 시도
  boot.initrd.availableKernelModules = [ "i2c_hid_acpi" "intel_lpss_pci" "intel_ishtp_hid" "intel_hid" "hid_multitouch" "i2c_i801" ];
  boot.initrd.kernelModules = [ "i2c_hid_acpi" ];

  boot.kernelModules = [ "ec_sys" ];
  boot.kernelParams = [
    "pcie_aspm=off"                   # PCIe 전원 관리로 인한 끊김 방지
    "i915.enable_psr=1"               # Intel 패널 셀프 리프레시 활성화
    "pci=nocms"                       # MSI 일부 모델에서 효과가 있는 PCI 설정
    "i2c_designware.disable_ps=1"     # 필수: I2C 컨트롤러의 절전 상태(Power State) 비활성화
    "psmouse.synaptics_intertouch=1"  # 핵심: 구형 PS/2 대신 I2C/SMBus 사용 강제
    "i8042.nopnp=1"                   # 핵심: 구형 PS/2 포트 자동 탐색 방지 (충돌 방지)
    "acpi_osi=Linux"                  # 추가: 메인보드의 윈도우 최적화 설정을 무시하고 리눅스 표준 사용
    "irqpoll"                         # 추가: 인터럽트 충돌 시 시스템이 하드웨어를 강제로 계속 체크 (프리징 방지)
  ];

  boot.blacklistedKernelModules = [
    "nouveau" "nvidia" "nvidia_drm" "nvidia_modeset"
    "psmouse" # 최신 I2C 터치패드와 충돌하는 구형 드라이버 차단
  ];
  boot.extraModprobeConfig = ''
    blacklist nouveau
    options nouveau modeset=0
    options ec_sys write_support=1
  '';

  fileSystems."/boot" =
    { device = "/dev/disk/by-uuid/57B8-D582";
      fsType = "vfat";
      options = [ "fmask=0022" "dmask=0022" ];
    };

  services.libinput.enable = true;

  # 부팅 시 I2C 버스 간섭을 일으킬 수 있는 서비스 비활성화
  networking.modemmanager.enable = false;
  services.fprintd.enable = false; # 지문 인식 초기화 시 프리징 발생 가능성 차단

  services.tlp = {
    enable = true;

    settings = {
      # 배터리 사용 시 CPU 성능 제한
      CPU_SCALING_GOVERNOR_ON_BAT = "powersave";
      CPU_ENERGY_PERF_POLICY_ON_BAT = "power";
      CPU_MAX_PERF_ON_BAT = 50;

      # AC 연결 시 설정
      CPU_SCALING_GOVERNOR_ON_AC = "balanced"; # 혹은 powersave (발열 제어 우선 시)
      CPU_ENERGY_PERF_POLICY_ON_AC = "balance_performance";
      CPU_MAX_PERF_ON_AC = 100;

      # 터보 부스트 제어 (가장 중요!)
      # AC에서도 터보 부스트를 꺼버리면(0), 절대 뜨거워지지 않는 '선비' 같은 노트북이 됩니다.
      CPU_BOOST_ON_BAT = 0;
      CPU_BOOST_ON_AC = 0;

      # 인텔 하이브리드 아키텍처 최적화
      # (선택 사항) 가벼운 작업 시 E-코어 우선 사용 유도
      SCHED_POWERSAVE_ON_AC = 1;
      SCHED_POWERSAVE_ON_BAT = 1;

      # 하드디스크 및 장치 절전
      SATA_LINKPWR_ON_BAT = "med_power_with_dipm";
      USB_AUTOSUSPEND = 0;
      USB_EXCLUDE_PHONE = 1; # 폰 연결 시 충전 방해 금지 (선택)
      USB_DENYLIST = "04f3:2ffa"; # lsusb에서 확인된 Elan Touchscreen을 블랙리스트에 추가

      # 배터리 <=> AC 전환간 최적화가 풀리는 현상 방지
      RUNTIME_PM_ON_AC = "auto";
      RUNTIME_PM_ON_BAT = "auto";
      # 터치패드는 절전에서 제외
      RUNTIME_PM_DENYLIST = "00:12.0 00:15.0";
      RUNTIME_PM_DRIVER_DENYLIST = "i2c_designware intel_ishtp intel_ishtp_hid intel_lpss_pci";

      # 배터리 모드에서도 Wi-Fi 절전 기능을 끕니다. (가장 중요)
      WIFI_PWR_ON_AC = "off";
      WIFI_PWR_ON_BAT = "off";

      # 덮개를 닫았을 때(배터리 모드) 무선 장치를 끄는 기능을 비활성화합니다.
      DEVICES_TO_DISABLE_ON_BAT_NOT_IN_USE = "";

      # VM writeback 해결
      MAX_LOST_WORK_SECS_ON_BAT = 60;
      MAX_LOST_WORK_SECS_ON_AC = 15;
    };
  };

  services.logind.settings.Login = {
    # 덮개를 닫았을 때 절전(Suspend) 방지
    HandleLidSwitch = "ignore";
    HandleLidSwitchExternalPower = "ignore";
    HandleLidSwitchDocked = "ignore";

    # 시스템이 절전 모드로 들어가기 전 대기 시간 (필요 시)
    IdleAction = "ignore";
  };

  # Wi-Fi 네트워크가 절전모드로 들어가지 않게끔 함
  networking.networkmanager.wifi.powersave = false;

  environment.systemPackages = with pkgs; [
    intel-media-driver # 하드웨어 가속용
    libva-vdpau-driver
    libvdpau-va-gl
  ];

  # MTU를 낮춰 Vivaldi 동기화 서버와의 문제 등을 회피함 (Tailscale, Double-NAT 등의 환경이 잦으므로 설정)
  networking.interfaces = {
    wlo1.mtu = 1400;
  };
}
