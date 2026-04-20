{mkHostConfiguration, ...}:
mkHostConfiguration ({
  pkgs,
  lib,
  ...
}: {
  os = {
    imports = [./iso.nixstrap.nix];

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

    # Firefox 등이 systemd-resolved를 통해 DNS 조회함 → 없으면 브라우저에서만 DNS 실패
    services.resolved.enable = true;

    # ISO 진단 도구
    environment.systemPackages = with pkgs; [
      parted
      pciutils # lspci
      usbutils # lsusb
    ];
  };

  hm = {
    home.username = "nixos";
    home.homeDirectory = "/home/nixos";

    home.packages = with pkgs; [
      zed-editor
    ];

    # == Hide Default Application Icons ==
    # (목적: 메뉴에서 불필요한 항목을 가려서 커스텀 인스톨러 느낌을 강화)
    # ~/.local/share/applications/ 가 시스템 경로보다 XDG 우선순위가 높으므로
    # systemPackages writeTextDir 방식보다 확실하게 덮어씌워진다.
    xdg.desktopEntries = {
      xterm = {
        name = "XTerm (Hidden)";
        noDisplay = true;
      };
      vim = {
        name = "Vim (Hidden)";
        noDisplay = true;
      };
      gvim = {
        name = "GVim (Hidden)";
        noDisplay = true;
      };
    };

    # base/home.nix의 SSH URL 리다이렉트 제거
    # base에서 url."git@github.com:".insteadOf = "https://github.com/" 를 설정하는데,
    # ISO는 SSH 키가 없으므로 https:// clone이 SSH로 리다이렉트되어 실패함
    programs.git.settings = lib.mkForce {
      user.name = "nixos";
      user.email = "nixos@localhost";
    };

    # (프리셋 mods는 flake.nix의 custom-iso extraModules에서 주입)
  };
})
