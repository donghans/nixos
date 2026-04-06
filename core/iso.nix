{
  pkgs,
  lib,
  metaConfig,
  ...
}: let
  # 1. setup.sh를 ISO 시스템의 bin 폴더에 넣기 위한 '패키지' 생성
  nixos-setup-from-repo-script = pkgs.writeShellApplication {
    name = "nixos-setup-from-repo"; # 실행될 명령어 이름

    # 스크립트 실행에 필요한 패키지들을 런타임에 보장
    runtimeInputs = [
      pkgs.jq
      pkgs.git
      pkgs.btrfs-progs
      pkgs.util-linux # mount, umount 등
    ];

    # core/scripts/iso.setup.sh 파일을 읽어와서 본문으로 사용
    text = builtins.readFile ./scripts/iso.setup.sh;
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
        echo "1. 자동 설치 (추천):"
        echo "   nixos-setup <EFI_PART> <ROOT_PART> <HOSTNAME>"
        echo ""
        echo "2. 다른 리포지토리 사용 시:"
        echo "   NIXOS_REPO=user/repo sudo -E \\"
        echo "   nixos-setup-from-repo <EFI_PART> <ROOT_PART> <HOSTNAME>"
        echo ""
        echo "예시 (nvme0n1 기기):"
        echo "   nixos-setup /dev/nvme0n1p1 /dev/nvme0n1p2 beelink-ser7-co"
        echo ""
        echo "TIP: 현재 기본 리포지토리는 '${metaConfig.nixosRepo}'로 설정되어 있습니다."
        echo "--------------------------------------------------"
      else
        echo "--------------------------------------------------"
        echo "🚀 NixOS Custom Installer (Hyprland)"
        echo "--------------------------------------------------"
        echo "To start the installation, enter the command below:"
        echo ""
        echo "1. Automatic Installation (Recommended):"
        echo "   nixos-setup <EFI_PART> <ROOT_PART> <HOSTNAME>"
        echo ""
        echo "2. Using a different repository:"
        echo "   NIXOS_REPO=user/repo sudo -E \\"
        echo "   nixos-setup-from-repo <EFI_PART> <ROOT_PART> <HOSTNAME>"
        echo ""
        echo "Example (nvme0n1 device):"
        echo "   nixos-setup /dev/nvme0n1p1 /dev/nvme0n1p2 beelink-ser7-co"
        echo ""
        echo "TIP: Default repository is set to '${metaConfig.nixosRepo}'."
        echo "--------------------------------------------------"
      fi
    fi
  '';

  # ISO에 기본적으로 포함하고 싶은 도구들
  environment.systemPackages = with pkgs; [
    parted
    disko # 만약 disko를 쓰신다면 유용합니다
    pciutils # lspci로 하드웨어 확인
    usbutils # lsusb
    nixos-setup-from-repo-script
  ];

  environment.shellAliases = {
    # 이제 터미널에서 'nixos-setup'만 치면 파라미터 입력 단계로 바로 넘어갑니다.
    # NIXOS_REPO 환경변수를 통해 setup 스크립트에 전달합니다.
    nixos-setup = "NIXOS_REPO=${metaConfig.nixosRepo} sudo -E nixos-setup-from-repo";
  };

  # == 프리셋: 워크스테이션 (그래픽 인스톨러 환경) ==
  mods._preset.workstation.enable = true;
  mods.gui.apps.vivaldi.enable = true; # (목적: ISO 내 브라우저 접근 제공)
}
