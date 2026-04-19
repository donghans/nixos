{
  pkgs,
  lib,
  metaConfig,
  ...
}: let
  # 1. lib 파일들을 Nix store에 바이트 복사 (문자열 인터폴레이션 없음 → 비 ASCII 안전)
  nixstrap-libs = pkgs.runCommand "nixstrap-libs" {} ''
    mkdir -p $out
    cp ${./scripts/nixstrap.lib-ui.sh}   $out/nixstrap.lib-ui.sh
    cp ${./scripts/nixstrap.lib-input.sh}   $out/nixstrap.lib-input.sh
    cp ${./scripts/nixstrap.lib-install.sh} $out/nixstrap.lib-install.sh
    cp ${./scripts/nixstrap.repo.py}        $out/nixstrap.repo.py
    cp ${./scripts/nixstrap.part.py}        $out/nixstrap.part.py
  '';

  # 2. nixstrap.sh를 ISO 시스템의 bin 폴더에 넣기 위한 '패키지' 생성
  #
  # nixstrap.sh shebang의 -p 목록을 파싱하여 runtimeInputs로 자동 주입.
  # → 도구 목록을 shebang 한 곳에서만 관리하고 여기서 중복 선언하지 않음.
  #
  # runtimeInputs의 두 가지 역할:
  #   (1) 실행 시 PATH 주입 — nixstrap이 nix-shell 없이도 python3·parted 등을 바로 사용
  #   (2) ISO 클로저 포함 — 오프라인 설치 환경에서도 해당 패키지가 /nix/store에 존재
  #
  # binary 이름을 nixstrap-wrapped로 분리하여 alias → binary 흐름을 명확히 함.
  # (alias nixstrap → sudo -E nixstrap-wrapped)
  _nixstrapPkgLine = builtins.elemAt (lib.splitString "\n" (builtins.readFile ./scripts/nixstrap.sh)) 1;
  # "#! nix-shell -i bash -p python3 git jq parted btrfs-progs util-linux"
  _nixstrapPkgStr = lib.removePrefix "#! nix-shell -i bash -p " _nixstrapPkgLine;
  nixstrapRuntimePkgs = map (name: pkgs.${name})
    (lib.filter (s: s != "") (lib.splitString " " _nixstrapPkgStr));

  nixstrap-wrapped = pkgs.writeShellApplication {
    name = "nixstrap-wrapped";

    runtimeInputs = nixstrapRuntimePkgs;

    # SCRIPT_DIR: nixstrap-libs store 경로로 주입 (lib 파일 탐색용)
    # NIXOS_REPO: ISO 빌드 시점의 레포 주소를 기본값으로 내장
    #   → alias는 sudo 권한 상승만 담당, 레포 설정은 binary 안에 캡슐화
    #   → 사용자가 Enter만 눌러도 올바른 레포가 선택됨 (변경도 가능)
    text =
      ''
        export SCRIPT_DIR="${nixstrap-libs}"
        export NIXOS_REPO="${metaConfig.nixosRepo}"
      ''
      + builtins.readFile ./scripts/nixstrap.sh;

    # 비 ASCII(한국어 주석 등) 대응을 위해 UTF-8 로케일 지정
    checkPhase = ''
      runHook preCheck
      export LC_ALL=C.UTF-8
      ${pkgs.stdenv.shellDryRun} "$target"
      ${pkgs.shellcheck}/bin/shellcheck -e SC1091,SC2034 "$target"
      runHook postCheck
    '';
  };
in {
  imports = [];

  # Plymouth 비활성화 (부팅 시 로그 확인 위함)
  boot.plymouth.enable = lib.mkForce false;

  # 부트로더 대기 시간 0초 (바로 부팅)
  boot.loader.timeout = lib.mkForce 0;

  # 커널 파라미터에서 로그 출력 터미널 지정
  boot.kernelParams = [
    "console=tty1" # 로그가 출력될 터미널 지정
  ];

  # 1. 'nixos' 기본 유저 활용 및 패스워드 생략 설정
  users.users.nixos = {
    # 패스워드 없이 sudo 사용 가능하게 (인스톨러 기본값 유지)
    initialHashedPassword = "";
  };

  # 2. 그래픽 환경 로그인 설정 (자동 로그인 비활성화)
  services.greetd.settings = {
    # 로그아웃하거나 세션이 종료되었을 때 보여줄 기본 화면 (tuigreet)
    default_session = {
      command = lib.mkForce (
        "${pkgs.tuigreet}/bin/tuigreet "
        + "--time "
        + "--greeting 'Welcome! Login as nixos (no password required)' "
        + "--cmd 'uwsm start hyprland-uwsm.desktop'"
      );
      user = "greeter";
    };
  };

  # 가끔 GDM이나 SDDM이 충돌을 일으킬 수 있으므로 명시적으로 꺼줍니다.
  services.displayManager.sddm.enable = lib.mkForce false;
  services.displayManager.gdm.enable = lib.mkForce false;

  # 3. TTY 자동 로그인 비활성화 (보안 및 사용자 선택 존중)
  # services.getty.autologinUser = lib.mkForce null; # 기본값으로 복구

  # 4. sudo 권한 강화 (패스워드 묻지 않음)
  security.sudo.wheelNeedsPassword = false;

  # 5. 환영 메시지 및 가이드 추가
  programs.zsh.interactiveShellInit = lib.mkAfter ''
    if [[ $(tty) == /dev/tty1 || $(tty) == /dev/pts/* ]]; then
      if [[ "$TERM" == "xterm-kitty" ]]; then
        echo "--------------------------------------------------"
        echo "🚀 NixOS 커스텀 인스톨러 (Hyprland 환경)"
        echo "--------------------------------------------------"
        echo "설치를 시작하려면 아래 명령어를 입력하세요:"
        echo ""
        echo "  nixstrap"
        echo ""
        echo "저장소·호스트·파티션 선택을 대화형으로 안내합니다."
        echo "레포에 없는 호스트명을 지정하면 프리셋(workstation/server)을"
        echo "물어보고 host.toml / configuration.nix / home.nix를 자동 생성합니다."
        echo "실패 시 이전 설정을 자동 저장하여 재시도할 수 있습니다."
        echo "--------------------------------------------------"
      else
        echo "--------------------------------------------------"
        echo "🚀 NixOS Custom Installer (Hyprland)"
        echo "--------------------------------------------------"
        echo "To start the installation, enter the command below:"
        echo ""
        echo "  nixstrap"
        echo ""
        echo "Interactively guides you through repo, host, and partition selection."
        echo "If a new hostname is given, a preset (workstation/server) will be"
        echo "prompted and host.toml / configuration.nix / home.nix auto-created."
        echo "On failure, your settings are saved and can be reloaded on retry."
        echo "--------------------------------------------------"
      fi
    fi
  '';

  # Firefox 등이 systemd-resolved를 통해 DNS 조회함 → 없으면 브라우저에서만 DNS 실패
  services.resolved.enable = true;

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

  # ISO에 기본적으로 포함하고 싶은 도구들
  environment.systemPackages = with pkgs; [
    parted
    pciutils # lspci
    usbutils # lsusb
    nixstrap-wrapped
  ];

  environment.shellAliases = {
    nixstrap = "sudo -E nixstrap-wrapped";
  };
}
