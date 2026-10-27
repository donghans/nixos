{mkHostConfiguration, ...}:
mkHostConfiguration ({
  pkgs,
  lib,
  ...
}: let
  # 기본 커널 인자(2026-10-20 변경). 이전에는 공통 설정(core.optimize.nix)이 `pcie_aspm=off`·`acpi_osi=Linux` 를, 이 호스트가 `irqpoll` 을 더 넣었으나 모두 뺐다:
  #  - 같은 조건(사무실 Wi-Fi, 덮개 닫힘, VT2)의 부팅 간 비교에서 옛 인자가 있을 때 **배터리 기준 쉬는 전력이 낮은 상태 +0.09 W(구분 안 됨)·높은 상태 +0.21 W(약 4%)**,
  #    패키지 절전도 얕았다(pc10 47→28%, pc8 45→30%). 누적 계량기로 확인한 배터리 V×I 기준(posture 가 아닌 power-evidence.md #28, #31).
  #  - irqpoll 은 터치패드 먹통 대응이었으나 진짜 원인(idma64 가 IRQ 27 을 공유)을 module_blacklist 로 막아 필요가 없어졌다(3시간 정상).
  #  - pcie_aspm=off / acpi_osi=Linux 는 일반 노트북용 기본값으로 들어간 것이고 이 기기에서 검증된 적이 없다.
  # 문제가 생기면(터치패드·키보드·밝기·PCIe 장치) 부팅 메뉴의 `legacy-quirks` 로 옛 구성으로 부팅할 수 있고, `with-*` 항목으로 인자를 하나씩 되살려 원인을 가릴 수 있다.
  # (목록을 통째로 지정하므로 확인은 `tr ' ' '\n' < /proc/cmdline`.)
  kernelBase = [
    "nowatchdog"
    "loglevel=3"
    "i915.enable_psr=1"
    "module_blacklist=idma64" # (아래 boot.kernelParams 주석 참고: idma64/IRQ 27 공유 → 터치패드 먹통의 진짜 원인 차단)
    "lsm=landlock,yama,bpf"
  ];
  legacy = ["pcie_aspm=off" "acpi_osi=Linux" "irqpoll"];
in {
  os = {
    imports = [
      ./msi-summit-me/touchpad-watchdog.nix
      ./msi-summit-me/hotspot-proxy-dispatcher.nix
      ./msi-summit-me/io-cost.nix
    ];

    # llm-utils-project 관련 테스트를 위해 임시로 열어둔 포트
    networking.firewall.allowedTCPPorts = [7681];

    # == SSH (beelink-ser7-co 한 대만) ==
    # (목적: 데스크톱에서 이 노트북을 원격 조작/시험. 다른 tailnet 사용자·기기에는 열지 않는다)
    # 접근 경계 3중: ① 22번 포트를 방화벽에 열지 않음(openFirewall=false) — tailscale 은 trustedInterfaces=["tailscale0"] 로만 닿는다
    #   ② 접속 출발지 IP 화이트리스트(AllowUsers, headscale 고정 IP) ③ 공개키는 beelink-ser7-co 것 하나, 비밀번호 인증 금지.
    services.openssh = {
      enable = true;
      openFirewall = false;
      settings = {
        PasswordAuthentication = false;
        KbdInteractiveAuthentication = false;
        AllowUsers = ["donghans@100.64.0.1"]; # beelink-ser7-co
      };
    };
    users.users.donghans.openssh.authorizedKeys.keys = [
      "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFfJ+1WOERxR/hBFrcgD2qGpNYXiU//1T4s6VRYkTRd1" # beelink-ser7-co
    ];

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
      # (idma64 차단 이유, 2026-10-19)
      # (이유, 2026-10-19: idma64(DMA 컨트롤러)가 i2c_designware 와 IRQ 27 을 공유해 DMA 모드에서 spurious interrupt 가 생기면
      #  irqpoll 이 필요하거나 "controller timed out" 폭주(2~3주에 한 번, 터치패드 먹통)가 났다. udev unbind 규칙은 부팅 때 안 걸리고
      #  (initrd 에서 이미 바인딩), `boot.blacklistedKernelModules`(= modprobe blacklist)도 **효과가 없었다**: intel_lpss 가 `softdep pre: platform:idma64` 를 가져서
      #  initrd 안에서(부팅 2초) 블랙리스트가 있는데도 로드됨(실제로 확인). 그래서 커널이 직접 로드를 거부하는 module_blacklist 를 쓴다(누가 요청하든, initrd 포함).
      #  기대 상태(런타임 실험으로 확인): idma64.0 장치만 있고 드라이버 없음 → i2c_designware 가 IRQ 27 단독(PIO), 터치패드 정상.
      #  재부팅 뒤 `lsmod | grep idma64` 가 비고 IRQ 27 이 i2c_designware.0 단독이면 성공 → 위 udev unbind 규칙은 지워도 됨. mods/_tools/desktop/posture/README.md 참고.)
      kernelParams = lib.mkForce kernelBase;

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

    # 부팅 메뉴(또는 `sudo bootctl set-oneshot nixos-generation-<N>-specialisation-<이름>.conf`)로 **한 번만** 고를 수 있는 항목(우선순위 40 = 기본의 mkForce 보다 높음):
    #  legacy-quirks : 이전 기본(옛 인자 3개 모두) — 문제가 생겼을 때 비상용
    #  with-aspm-off / with-irqpoll / with-osi-linux : 기본에 인자 **하나만** 되살림 — 문제가 생겼을 때 어느 인자가 필요한지 가리는 용도(반응형으로만 사용)
    specialisation.legacy-quirks.configuration.boot.kernelParams = lib.mkOverride 40 (kernelBase ++ legacy);
    specialisation.with-aspm-off.configuration.boot.kernelParams = lib.mkOverride 40 (kernelBase ++ ["pcie_aspm=off"]);
    specialisation.with-irqpoll.configuration.boot.kernelParams = lib.mkOverride 40 (kernelBase ++ ["irqpoll"]);
    specialisation.with-osi-linux.configuration.boot.kernelParams = lib.mkOverride 40 (kernelBase ++ ["acpi_osi=Linux"]);

    # (이유: TLP RUNTIME_PM_DENYLIST는 TLP 서비스 시작 후 적용되어 부팅 초기 probe 시점엔 늦음.
    #  kernel 6.18+ 에서 i2c_designware 모듈이 없어 disable_ps 파라미터도 무효가 됨.
    #  I2C 컨트롤러(0x51e8)가 runtime suspend 상태로 터치패드 probe 실패 방지를 위해
    #  udev add 타이밍에 직접 power/control=on 강제.)
    #
    # (idma64.0 과 i2c_designware.0 의 IRQ 27 공유 문제는 udev 규칙이 아니라 커널 인자 `module_blacklist=idma64` 로 해결했다 — 위 kernelParams 주석.
    #  예전의 "bind 때 idma64.0 unbind" 규칙은 initrd 에서 이미 바인딩돼 부팅 때 걸리지 않아 2026-10-19 에 제거.)
    services.udev.extraRules = ''
      ACTION=="add", SUBSYSTEM=="pci", ATTR{vendor}=="0x8086", ATTR{device}=="0x51e8", ATTR{power/control}="on"
      # 터치스크린 USB 절전(hypr-input-policy)이 root 없이 power/control 에 쓸 수 있게: users 그룹 쓰기 허용(해당 장치만)
      ACTION=="add", SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="04f3", ATTR{idProduct}=="2ffa", RUN+="${pkgs.coreutils}/bin/chgrp users /sys%p/power/control", RUN+="${pkgs.coreutils}/bin/chmod g+w /sys%p/power/control"
      # AC 어댑터를 꽂거나 뽑을 때만(POWER_SUPPLY_NAME=ADP1) kfence-policy 를 부른다(배터리 잔량 변화 이벤트에는 부르지 않음)
      SUBSYSTEM=="power_supply", ACTION=="change", ENV{POWER_SUPPLY_NAME}=="ADP1", TAG+="systemd", ENV{SYSTEMD_WANTS}+="kfence-policy.service"
    '';

    # == KFENCE(커널 메모리 오류 샘플링 검사) — 배터리 때는 끄고 AC 일 때만 켠다 ==
    # KFENCE 는 100ms 마다 할당 하나를 보호 페이지에 두고 잘못된 접근(해제 후 사용·범위 밖 접근)을 리포트하는 버그 탐지기이고, 타이머가 초당 약 10번 CPU 를 깨운다.
    # 끄면 쉬는 psys 가 약 0.15 W 낮다(장부 #124, 4쌍 모두 같은 방향, 추정 — 전부 패키지 몫 #137). 배터리에서는 이 상시 깨움을 남기지 않고, AC 일 때는 한 번에 찾을 수 있게 켜 둔다.
    # 런타임 쓰기라 재부팅이 필요 없고 되돌리기도 즉시다(커널 로그에 `kfence: disabled` / `re-enabled`). 부팅 때와 AC 어댑터 변화(udev, 위)마다 현재 전원에 맞춘다.
    # 값 100 은 커널 기본(CONFIG_KFENCE_SAMPLE_INTERVAL=100)과 같다. 배터리 때 끄므로 그동안의 메모리 오류는 리포트되지 않는다 — 터졌는지는 `journalctl -k | grep -c "BUG: KFENCE"` 로 센다
    # (지금까지 5일·부팅 29번 동안 0건). 2번 이상 나오면 확인한다. 정책을 끄려면 이 서비스와 위 udev 규칙 한 줄을 지운다.
    systemd.services.kfence-policy = {
      description = "KFENCE sampling: on at AC, off on battery (runtime)";
      wantedBy = ["multi-user.target"];
      serviceConfig.Type = "oneshot";
      script = ''
        p=/sys/module/kfence/parameters/sample_interval
        [ -w "$p" ] || exit 0
        if [ "$(cat /sys/class/power_supply/ADP1/online 2>/dev/null)" = 1 ]; then v=100; else v=0; fi
        [ "$(cat "$p")" = "$v" ] || echo "$v" > "$p"
      '';
    };

    # == Services & Hardware ==
    # (목적: 부팅 시 I2C 버스 간섭 방지)
    networking.modemmanager.enable = false;
    # (지문 인식은 쓰지 않음: Goodix 27c6:6094 센서는 동작했지만, 지문이 비밀번호보다 먼저 PAM 에서 처리돼
    #  비밀번호만 쓰려면 지문 실패를 기다려야 했고 keyring 도 못 열었음 → fprintd 를 끄고 얼굴 인식으로 대체)

    # == 얼굴 인식 (Howdy + IR 카메라) ==
    # 카메라: SunplusIT FHD Camera(5986:213a) — 일반(RGB)과 IR 가 별개 영상 장치. Howdy 는 IR 장치를 써야 함.
    # IR 에미터는 IR 스트림을 열면 별도 설정 없이 켜지는 것으로 확인됨(linux-enable-ir-emitter 불필요).
    # 적용 범위: hyprlock(잠금 화면)만. greetd(로그인)/sudo/su/TTY/polkit 은 비밀번호만(로그인은 비밀번호로 해야
    #   gnome-keyring 이 같이 열리고, 앉아만 있어도 통과하는 얼굴 인증을 권한 상승에 쓰지 않기 위함). 얼굴 인식은 "sufficient" 라 카메라가 없거나 꺼져 있거나
    #   얼굴이 안 맞으면 자동으로 비밀번호로 넘어감.     # 얼굴 등록(root 필요): sudo howdy add   /  확인: sudo howdy list   /  삭제: sudo howdy clear
    services.howdy = {
      enable = true;
      control = "sufficient";
      # (이유: /dev/video2 같은 번호는 부팅마다 바뀔 수 있어 USB 포트·인터페이스(1.2 = IR) 기준의 고정 경로 사용)
      settings.video.device_path = "/dev/v4l/by-path/pci-0000:00:14.0-usb-0:7:1.2-video-index0";
    };
    security.pam.howdy.enable = false; # (이유: 기본값은 모든 PAM 서비스에 적용되므로 끄고 아래 한 곳만 켬)
    security.pam.services.hyprlock.howdy.enable = false; # (2026-10-17 끔: 잠금 중 pam_howdy 가 ~37분 멈춰 비밀번호 입력창이 안 떴음. pam_howdy 는 비밀번호 프롬프트 전에 동기 실행돼 timeout=4 가 안 먹으면 잠금 해제 불가. 재현은 안 됨(pamtester 로 5초 만에 정상))

    # == eDP 패널 PSR1 강제 켜기 ==
    # 펌웨어 VBT 가 이 패널의 PSR 을 꺼 두어(`PSR disabled by flag`) `i915.enable_psr=1` 이 무시된다. debugfs `i915_edp_psr_debug`=2 는 VBT 를 무시하게 하며
    # 다음 모드셋부터 적용되므로 링크 재훈련으로 모드셋을 한 번 일으킨다(부팅 중 화면이 잠깐 깜빡임). 측정: psys −0.35 W·배터리 −0.44 W(_docs/…/power-evidence.md #54, #56).
    # 화면 이상(깜빡임·잔상)이 보이면 이 서비스를 끄면 된다: `sudo systemctl disable --now psr-force`(끄면 다음 부팅부터 원래대로).
    systemd.services.psr-force = {
      description = "Force eDP PSR1 on (override VBT disable)";
      wantedBy = ["multi-user.target"];
      serviceConfig.Type = "oneshot";
      serviceConfig.RemainAfterExit = true;
      script = ''
        for d in /sys/kernel/debug/dri/*/; do
          [ -e "$d/i915_edp_psr_debug" ] || continue
          echo 2 > "$d/i915_edp_psr_debug"
          echo 1 > "$d/eDP-1/i915_dp_force_link_retrain"
        done
      '';
      preStop = ''
        for d in /sys/kernel/debug/dri/*/; do
          [ -e "$d/i915_edp_psr_debug" ] && echo 0 > "$d/i915_edp_psr_debug"
        done
      '';
    };

    # == 터치패드 재인식 (장치 메뉴의 "터치패드 재인식" 항목) ==
    # 터치패드(ELAN0305, I2C HID)가 먹통이 될 때 드라이버를 unbind/bind 해서 다시 인식시킴.
    # sysfs 쓰기는 root 만 가능하므로 root 서비스로 두고, 로컬 활성 세션 사용자가 비밀번호 없이 이 유닛만 시작하게 허용.
    systemd.services.touchpad-reset = {
      description = "Re-probe ELAN0305 touchpad (i2c_hid_acpi unbind/bind)";
      serviceConfig.Type = "oneshot";
      script = ''
        drv=/sys/bus/i2c/drivers/i2c_hid_acpi
        dev=i2c-ELAN0305:00
        [ -e "$drv/$dev" ] && echo "$dev" > "$drv/unbind"
        sleep 1
        echo "$dev" > "$drv/bind"
      '';
    };
    security.polkit.extraConfig = ''
      polkit.addRule(function(action, subject) {
        if (action.id == "org.freedesktop.systemd1.manage-units" &&
            action.lookup("unit") == "touchpad-reset.service" &&
            subject.local && subject.active) {
          return polkit.Result.YES;
        }
      });
      // 덮개 닫힘/열림에 TLP 프로필을 바꾸는 root 유닛(아래)도 같은 방식으로 허용
      polkit.addRule(function(action, subject) {
        if (action.id == "org.freedesktop.systemd1.manage-units" &&
            ["tlp-lid-closed.service", "tlp-lid-open.service"].indexOf(action.lookup("unit")) >= 0 &&
            subject.local && subject.active) {
          return polkit.Result.YES;
        }
      });
    '';

    # == 덮개를 닫으면 TLP 배터리 프로필, 열면 자동 모드 ==
    # `tlp bat` 은 전원과 무관하게 배터리 프로필을 적용하고 수동 모드로 들어가며(전원이 바뀌어도 무시), `tlp start` 는 실제 전원에 맞는 프로필을 적용하고 수동 모드에서 나온다(TLP 1.9.1 매뉴얼).
    # tlp 는 root 가 필요해서 사용자 서비스(lid-policy)가 직접 부르면 "Error: missing root privilege." 로 실패했다(2026-10-19 로그). 위 touchpad-reset 과 같은 방식으로
    # root 유닛을 두고 polkit 으로(위 touchpad-reset 규칙 옆에 추가) 로컬 활성 세션 사용자가 이 두 유닛만 시작하게 한다. lid-policy 가 아래 lidSwitch*ExtraCmd 로 시작한다.
    systemd.services.tlp-lid-closed = {
      description = "TLP battery profile while the lid is closed";
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${pkgs.tlp}/bin/tlp bat";
      };
    };
    systemd.services.tlp-lid-open = {
      description = "Resume TLP automatic mode when the lid is opened";
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${pkgs.tlp}/bin/tlp start";
      };
    };
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

    # Wi-Fi 절전은 **배터리에서만** 켠다(2026-10-20; 예전 목적은 "절전 방지"=연결 끊김 방지였다). 공통 노트북 설정(core.power.nix)은 AC/배터리 모두 끄고
    # NetworkManager 도 `wifi.powersave=false` 로 강제하는데, 덮개를 닫은 쉬는 상태에서 켜면 배터리 약 −0.6 W(+패키지가 pc10 까지 진입)였다(ABAB 시험, mods/_tools/desktop/posture/README.md).
    # NM 이 TLP 값을 덮어쓰지 못하도록 NM 쪽 강제를 풀고(null) TLP 가 AC=off, 배터리=on 으로 정한다. 대가: 지연이 늘 수 있음(핫스팟에서 가장 조심).
    # 되돌리려면 이 블록을 `networking.networkmanager.wifi.powersave = false;` 한 줄로 바꾸면 된다(TLP 배터리 값은 공통 설정의 off 로 돌아감).
    services.tlp.settings.WIFI_PWR_ON_BAT = lib.mkForce "on";
    networking.networkmanager.wifi.powersave = lib.mkForce null;

    programs.appimage = {
      enable = true;
      binfmt = true;
    };

    # 영상 하드웨어 디코딩(VA-API): 드라이버는 /run/opengl-driver/lib/dri 에 있어야 libva 가 찾음.
    # systemPackages 에 넣으면 /run/current-system/sw/lib/dri 에 놓이는데 libva 는 거기를 찾지 않아서
    # `vainfo` 가 iHD_drv_video.so 를 못 찾고 실패했음(경로를 직접 지정하면 H264/HEVC 등이 정상으로 나옴)
    hardware.graphics.extraPackages = with pkgs; [
      intel-media-driver
    ];

    environment.systemPackages = with pkgs; [
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
    # HDMI/DisplayPort 오디오 출력(HDMI1~3)을 숨김 — 사용자가 모니터 오디오를 쓰지 않음(2026-10-19).
    # 이 노트북의 오디오 칩에는 모니터 연결과 상관없이 HDMI/DP 출력 3개가 항상 있고, pasystray 가 다시 시작될 때마다
    # 이 출력들을 "새 장치"로 반복해서 알려서 알림 기록(notif)이 쌓였음. 노드 이름 예: alsa_output.pci-…skl_hda_dsp_generic.HiFi__HDMI1__sink
    # 적용은 `systemctl --user restart wireplumber` (음이 잠깐 끊김). 되돌리려면 이 블록을 지우고 같은 명령.
    xdg.configFile."wireplumber/wireplumber.conf.d/51-no-hdmi-audio.conf".text = ''
      monitor.alsa.rules = [
        {
          matches = [ { node.name = "~alsa_output\\..*HiFi__HDMI[0-9]+__sink" } ]
          actions = { update-props = { node.disabled = true } }
        }
      ]
    '';

    # 텍스트 입력 커서(캐럿) 깜빡임 끔(2026-10-25). Vivaldi 입력창의 깜빡임이 0.5초마다 화면을 갱신시켜 화면 절전(PSR)을
    # 약 29% 깨고 있었음(장부 #110: PSR 71%→99.5%, 앱 CPU −62%, psys 약 −1.6 W, 2쌍). GTK·Chromium 앱에 적용(Zed·kitty 는 자체 설정).
    # 새로 시작하는 앱부터 적용. 되돌리려면 이 두 줄을 지움.
    gtk.gtk3.extraConfig.gtk-cursor-blink = false;
    gtk.gtk4.extraConfig.gtk-cursor-blink = false;

    # Zed 편집기 커서 깜빡임 끔(2026-10-25). Zed 는 GTK 설정을 읽지 않고 자체 `cursor_blink` 를 쓴다. 포커스된 편집기·Git 그래프 검색칸의
    # 캐럿이 0.5초마다 화면을 갱신시켜 PSR 을 깨고 있었음(장부 #114: 갱신 40회/20초→0~1, 실제 프로젝트 PSR 약 67%→). 새로 시작하는 Zed 부터,
    # 열려 있는 Zed 는 settings.json 변경을 바로 반영. settings.json 은 Zed 가 다시 쓰므로(zed.nix 와 같은 이유) 키 하나만 활성화 때 맞춘다.
    # 되돌리려면 이 블록을 지우고 settings.json 의 "cursor_blink" 줄을 지움.
    home.activation.zedCursorBlink = lib.hm.dag.entryAfter ["writeBoundary"] ''
      conf="$HOME/.config/zed/settings.json"
      if [ -z "''${DRY_RUN:-}" ] && [ -f "$conf" ]; then
        if ${pkgs.gnugrep}/bin/grep -q '"cursor_blink"' "$conf"; then
          ${pkgs.gnused}/bin/sed -i 's|"cursor_blink": *[a-z]*|"cursor_blink": false|' "$conf"
        else
          ${pkgs.gnused}/bin/sed -i '0,/^{/s|^{|{\n  "cursor_blink": false,|' "$conf"
        fi
      fi
    '';

    # 실패한 서비스 확인(notif-health)을 1분 → 5분마다로(2026-10-25). 이 노트북에서 주기 타이머 두 개(터치패드 감시 30초 + 이것 60초)를
    # 끄면 쉬는 전력이 약 −0.26 W(장부 #121, 3쌍). 실패 알림이 최대 5분 늦어질 뿐. 공통 모듈(mods/gui/utils/notify-logger.nix)의 기본값은 그대로.
    systemd.user.timers.notif-health.Timer = {
      OnUnitActiveSec = lib.mkForce "300s";
      AccuracySec = lib.mkForce "60s";
    };

    # 런처에서 Howdy 설정 GUI(howdy-gtk)는 숨김 — 얼굴 등록/삭제는 CLI(sudo howdy add / clear)로 함
    xdg.desktopEntries.howdy = {
      name = "Howdy";
      exec = "howdy-gtk";
      noDisplay = true;
    };

    wayland.windowManager.hyprland = {
      touchpadToggleKey = "SUPER + CTRL, F24";
      internalKeyboardName = "at-translated-set-2-keyboard"; # (텐트/태블릿에서 정책이 끄는 내장 키보드)
      touchscreenUsbId = "04f3:2ffa"; # (ELAN 터치스크린: 터치를 꺼 둔 동안만 USB 절전 — 덮개 닫은 쉬는 상태 실측 약 −0.5 W)

      # 터치스크린/펜은 노트북 패널 전용 입력 장치. 지정하지 않으면 좌표가 모든 모니터를 합친 영역에 매핑돼
      # 외부 모니터와 확장하면 외부 모니터 기준으로 인식됨(터치가 엉뚱한 위치로 들어감).
      # (주의: 전역 input:touchdevice:output 만으로는 부족했고 장치별 지정으로 해결됨 — 실제 터치로 확인)
      # (주의: hyprctl reload 는 런타임 설정을 지우므로 화면 모드 메뉴 등이 reload 해도 유지되게 설정 파일에 둠)
      extraConfig = ''
        hl.device({ name = "elan-touchscreen", output = "eDP-1" })
        hl.device({ name = "elan-touchscreen-stylus", output = "eDP-1" })
      '';
      deviceMenuExtraEntries = [
        {
          label = "터치패드 재인식 (드라이버 재시작)";
          # 재시작하면 장치가 기본(켜짐)으로 돌아오므로 메뉴가 보여 주는 상태 기록도 켜짐으로 맞춤
          command = "systemctl start touchpad-reset.service && mkdir -p ~/.local/state/hypr && echo true > ~/.local/state/hypr/touchpad_enabled";
        }
      ];
      lidSwitchOnExtraCmd = "systemctl start --no-block tlp-lid-closed.service"; # (root 필요: 위 유닛 + polkit)
      lidSwitchOffExtraCmd = "systemctl start --no-block tlp-lid-open.service";
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
