{ pkgs, lib, metaConfig, ... }: let
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

    # iso/setup.sh 파일을 읽어와서 본문으로 사용
    text = builtins.readFile ./setup.sh;
  };
in {
  imports = [ ./lib/hyprland.nix ];

  # 부트로더 대기 시간 0초 (바로 부팅)
  boot.loader.timeout = lib.mkForce 0;

  # 커널 파라미터에서 부팅을 조용하게 만드는 요소들 제거
  boot.kernelParams = [
    "console=tty1"        # 로그가 출력될 터미널 지정
  ];

  # 혹시 graphical-base 모듈에 의해 Plymouth가 켜져 있다면 강제로 끕니다.
  boot.plymouth.enable = lib.mkForce false;

  # 1. 'nixos' 기본 유저 활용 및 패스워드 생략 설정
  users.users.nixos = {
    # 패스워드 없이 sudo 사용 가능하게 (인스톨러 기본값 유지)
    initialHashedPassword = "";
  };

  # 2. 그래픽 환경 자동 로그인 설정
  # 기존 tuigreet 설정을 아래와 같이 덮어씁니다.
  services.greetd.settings = {
    # [핵심] 부팅 시 자동으로 실행될 세션
    initial_session = {
      # uwsm을 사용한다면 아래와 같이 실행하는 것이 가장 정확합니다.
      command = "uwsm start hyprland-uwsm.desktop";
      user = "nixos";
    };

    # 로그아웃하거나 세션이 종료되었을 때 보여줄 기본 화면 (tuigreet)
    default_session = {
      command = lib.mkForce "${pkgs.greetd.tuigreet}/bin/tuigreet --time --remember --cmd 'uwsm start hyprland-uwsm.desktop'";
      user = "greeter";
    };
  };

  # 가끔 GDM이나 SDDM이 충돌을 일으킬 수 있으므로 명시적으로 꺼줍니다.
  services.displayManager.sddm.enable = lib.mkForce false;
  services.xserver.displayManager.gdm.enable = lib.mkForce false;

  # 3. TTY 자동 로그인도 'nixos'로 변경
  services.getty.autologinUser = lib.mkForce "nixos";

  # 4. sudo 권한 강화 (패스워드 묻지 않음)
  security.sudo.wheelNeedsPassword = false;

  # ISO에 기본적으로 포함하고 싶은 도구들
  environment.systemPackages = with pkgs; [
    parted
    disko # 만약 disko를 쓰신다면 유용합니다
    pciutils # lspci로 하드웨어 확인
    usbutils # lsusb
    nixos-setup-from-repo-script
  ];

  environment.shellAliases = {
    # GH_USER를 미리 박아둔 단축어
    # 이제 터미널에서 'nixos-setup'만 치면 파라미터 입력 단계로 바로 넘어갑니다.
    nixos-setup = "GH_USER=${metaConfig.gitName} sudo -E nixos-setup-from-repo";
  };
}
