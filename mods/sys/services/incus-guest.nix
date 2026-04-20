{mkMod, ...}:
mkMod __curPos "Incus VM Guest (agent + SPICE vdagent + serial console)" ({
  pkgs,
  lib,
  isISO,
  ...
}: {
  os =
    {
      # (목적: incus exec 동작에 필요한 게스트 에이전트)
      # incus-agent가 실행 중이어야 호스트에서 incus exec로 VM 셸 접근 가능.
      virtualisation.incus.agent.enable = true;
      # (목적: SPICE 뷰어 ↔ VM 간 클립보드 공유)
      services.spice-vdagentd.enable = true;
      # (목적: incus console 명령으로 시리얼 콘솔 접근 가능하게)
      # ttyS0 시리얼 콘솔을 활성화해야 incus console이 출력을 표시함
      boot.kernelParams = ["console=ttyS0"];
      systemd.services."serial-getty@ttyS0".enable = true;
    }
    // lib.optionalAttrs isISO {
      # ── Firefox 네트워크 수정 (incus NAT VM + filter-AAAA 환경) ──────────────────
      #
      # 증상: curl/ping/DNS는 정상이나 Firefox만 수 분간 멈췄다가 연결 실패.
      #
      # 원인 분석:
      #
      # 1. OCSP 스테이플링 실시간 조회 (가장 큰 원인)
      #    Firefox는 HTTPS 인증서의 폐기 여부를 OCSP 서버(ocsp.digicert.com 등)에
      #    실시간으로 확인한다. 이 요청이 VM → NAT → 호스트 nftables → 인터넷으로
      #    나가야 하는데, 호스트 nftables의 forward 체인 정책(drop)이 VM에서 발생하는
      #    OCSP TCP 연결을 차단하거나 지연시킬 수 있다.
      #    curl은 OCSP를 확인하지 않으므로 영향 없음.
      #    security.OCSP.enabled = false 로 비활성화.
      #
      # 2. DNS-over-HTTPS (DoH) 자동 감지 시도
      #    Firefox는 기본적으로 Cloudflare(1.1.1.1:443) DoH로 업그레이드를 시도한다.
      #    filter-AAAA dnsmasq 설정으로 인해 AAAA 레코드가 없으면 DoH 감지 로직이
      #    NXDOMAIN을 받고 재시도를 반복한다. 또한 DoH 자체가 TCP:443으로 나가야 하는데
      #    nftables forward drop에서 막힐 수 있다.
      #    network.trr.mode = 5 (DoH 완전 비활성화) 로 해결.
      #
      # 3. IPv6 연결 시도 (Happy Eyeballs)
      #    filter-AAAA로 AAAA를 막아도 Firefox 내부의 IPv6 소켓 바인딩 시도 자체는
      #    OS 레벨에서 발생한다. VM 커널에 IPv6가 활성화된 경우 링크-로컬(fe80::)
      #    주소를 갖고 있어, Happy Eyeballs 알고리즘이 IPv6 연결을 먼저 시도하고
      #    타임아웃(약 300ms) 후 IPv4로 폴백한다. 이 과정이 수백 개의 연결에서
      #    쌓이면 전체적으로 수 분의 지연으로 나타난다.
      #    network.dns.disableIPv6 = true 로 DNS 레벨 차단.
      #
      # 4. 캡티브 포털 감지
      #    Firefox는 시작 시 detectportal.firefox.com 에 HTTP 요청을 보낸다.
      #    이 요청이 실패하거나 타임아웃되면 일부 기능이 느려질 수 있다.
      #    network.captive-portal-service.enabled = false 로 비활성화.
      #
      # 5. 네트워크 연결성 체크
      #    Firefox는 connectivity-check.mozilla.org 로 연결성을 주기적으로 확인한다.
      #    network.connectivity-service.enabled = false 로 비활성화.
      #
      # 참고: filter-AAAA는 dnsmasq가 AAAA 응답을 걸러내는 것이지, OS의 IPv6
      # 스택을 비활성화하지 않는다. Firefox는 DNS와 무관하게 IPv6 소켓을 시도하므로
      # about:config에서 명시적으로 비활성화해야 한다.
      #
      # programs.firefox.enable = true 가 필요: installation-cd-graphical-base.nix는
      # Firefox를 environment.defaultPackages로 추가할 뿐 programs.firefox 모듈을
      # 활성화하지 않는다. enable = true 없이는 policies/preferences가 적용되지 않는다.
      programs.firefox = {
        enable = true;
        # preferencesStatus = "locked": 사용자가 about:config에서 변경 불가
        # "default"로 설정하면 사용자가 덮어쓸 수 있음 (ISO는 ephemeral이므로 locked 적합)
        preferencesStatus = "locked";
        preferences = {
          # 1. OCSP 실시간 폐기 확인 비활성화
          #    OCSP 서버 접근 실패 시 Firefox가 수 분간 멈추는 주요 원인
          "security.OCSP.enabled" = 0;

          # 2. DNS-over-HTTPS 완전 비활성화
          #    0=기본꺼짐, 1=경쟁모드, 2=항상DoH, 3=DoH전용, 4=shadowing, 5=완전비활성화
          "network.trr.mode" = 5;

          # 3. Firefox DNS 레벨 IPv6 비활성화
          #    filter-AAAA가 dnsmasq에서 AAAA를 막아도, Firefox는 OS에 직접
          #    IPv6 소켓을 열려고 시도함 → Happy Eyeballs 지연 방지
          "network.dns.disableIPv6" = true;

          # 4. 캡티브 포털 감지 비활성화
          #    시작 시 detectportal.firefox.com 요청이 타임아웃되면 지연 발생
          "network.captive-portal-service.enabled" = false;

          # 5. 네트워크 연결성 체크 비활성화
          "network.connectivity-service.enabled" = false;
        };
      };
    };

  hm = {
    # spice-vdagent (유저 세션 에이전트) 자동 시작
    # spice-vdagentd(system daemon, os 블록에서 활성화)가 virtio-serial을 담당하고,
    # spice-vdagent(user session)가 클립보드·해상도 등 유저 세션 기능을 담당한다.
    # 유저 세션 에이전트는 자동으로 시작되지 않으므로 Hyprland exec-once로 실행.
    wayland.windowManager.hyprland.settings.exec-once = [
      "${pkgs.spice-vdagent}/bin/spice-vdagent"
    ];

    # Wayland → X11 클립보드 브릿지
    #
    # NixOS nixpkgs의 spice-vdagent는 GTK3 없이 빌드되어 순수 X11 전용이다.
    # Wayland 클립보드를 직접 볼 수 없고 DISPLAY=:0 (XWayland)의 X11 클립보드만 감시한다.
    # Hyprland의 자체 Wayland→X11 동기화가 VM 환경에서 불안정하므로,
    # wl-paste --watch로 Wayland 클립보드 변화를 직접 감지해 X11에 써줌으로써
    # spice-vdagent가 변화를 감지 → SPICE 채널 → 호스트 클립보드로 이어지게 한다.
    #
    # 반대 방향(X11→Wayland)은 wl-clip.nix의 x11-clipboard-bridge가 이미 담당.
    systemd.user.services.wayland-x11-clipboard-bridge = {
      Unit = {
        Description = "Wayland to X11 clipboard bridge for spice-vdagent";
        After = ["graphical-session.target"];
        PartOf = ["graphical-session.target"];
      };
      Service = {
        ExecStart = "${pkgs.wl-clipboard}/bin/wl-paste --type text/plain --watch ${pkgs.xclip}/bin/xclip -selection clipboard -i";
        Restart = "on-failure";
        RestartSec = "2";
      };
      Install.WantedBy = ["graphical-session.target"];
    };
  };
})
