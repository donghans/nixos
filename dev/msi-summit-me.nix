{ config, pkgs, ... }: {
  imports = [
    ./hardware/msi-summit-me.nix
    ./base/developer.nix
  ];

  boot.kernelModules = [ "ec_sys" ];
  boot.kernelParams = [
    "pcie_aspm=off"                   # PCIe 전원 관리로 인한 끊김 방지
    "i915.enable_psr=1"               # Intel 패널 셀프 리프레시 활성화
    "i8042.nopnp"                     # PnP 기능이 문제를 일으킬 때 강제 비활성화
    "pci=nocms"                       # MSI 일부 모델에서 효과가 있는 PCI 설정
    "psmouse.synaptics_intertouch=0"  # Synaptics 패드일 경우 I2C 대신 PS/2 모드 강제
  ];

  boot.blacklistedKernelModules = [ "nouveau" "nvidia" "nvidia_drm" "nvidia_modeset" ];
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

  # 절전 설정 (발열 제어)
  powerManagement.powertop.enable = true;

  # NVIDIA Fine Grained Control(정밀 제어): GPU를 미사용중이므로 대기전력 자체를 없애버려 발열 제어
  hardware.nvidia.powerManagement.finegrained = true;

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
      USB_AUTOSUSPEND = 1;
      USB_EXCLUDE_PHONE = 1; # 폰 연결 시 충전 방해 금지 (선택)

      # 배터리 <=> AC 전환간 최적화가 풀리는 현상 방지
      RUNTIME_PM_ON_AC = "auto";
      RUNTIME_PM_ON_BAT = "auto";

      # 배터리 모드에서도 Wi-Fi 절전 기능을 끕니다. (가장 중요)
      WIFI_PWR_ON_AC = "off";
      WIFI_PWR_ON_BAT = "off";

      # 덮개를 닫았을 때(배터리 모드) 무선 장치를 끄는 기능을 비활성화합니다.
      DEVICES_TO_DISABLE_ON_BAT_NOT_IN_USE = "";
    };
  };

  services.udev.extraRules = ''
    # 터치패드 전원 관리 강제 활성화 (자동 절전 방지)
    # ELAN0305:00 04F3:31FD Touchpad 장치에 대해 절전 기능을 끕니다.
    ACTION=="add", SUBSYSTEM=="i2c", ATTR{name}=="ELAN0305:00 04F3:31FD Touchpad", ATTR{power/control}="on"

    # 전원 어댑터 상태가 바뀔 때마다 (AC -> BAT, BAT -> AC) powertop 자동 최적화 실행
    SUBSYSTEM=="power_supply", ATTR{online}=="0", RUN+="${pkgs.powertop}/bin/powertop --auto-tune"
    SUBSYSTEM=="power_supply", ATTR{online}=="1", RUN+="${pkgs.powertop}/bin/powertop --auto-tune"
  '';

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
