{mkHostConfiguration, ...}:
mkHostConfiguration ({
  pkgs,
  lib,
  ...
}: {
  os = {
    imports = [
      ./msi-summit-me/touchpad-watchdog.nix
      ./msi-summit-me/hotspot-proxy-dispatcher.nix
      ./msi-summit-me/io-cost.nix
    ];

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

    # (목적: Wi-Fi 네트워크 절전 방지)
    networking.networkmanager.wifi.powersave = false;

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

    # 런처에서 Howdy 설정 GUI(howdy-gtk)는 숨김 — 얼굴 등록/삭제는 CLI(sudo howdy add / clear)로 함
    xdg.desktopEntries.howdy = {
      name = "Howdy";
      exec = "howdy-gtk";
      noDisplay = true;
    };

    wayland.windowManager.hyprland = {
      touchpadToggleKey = "SUPER + CTRL, F24";
      internalKeyboardName = "at-translated-set-2-keyboard"; # (텐트/태블릿에서 정책이 끄는 내장 키보드)

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
