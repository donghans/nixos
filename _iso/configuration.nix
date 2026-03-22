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
  imports = [
    ./lib/hyprland.nix
  ];

  # Root 자동 로그인 설정 (tty1)
  services.getty.autologinUser = lib.mkForce "root";

  # greetd가 활성화되어 있을 경우를 대비한 강제 비활성화
  # 만약 GUI가 필요 없는 설치 전용이라면 lib.mkForce로 꺼버립니다.
  services.greetd.enable = lib.mkForce false;

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
