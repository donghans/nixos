{
  pkgs,
  lib,
  metaConfig,
  ...
}: {
  programs = {
    home-manager.enable = true;
    zsh.enable = true; # (목적: 사용자별 .zshrc를 생성하여 초기 설치 메시지 차단)
    atuin = {
      enable = true;
      settings = {
        search = {
          filters = ["host" "directory"];
        };
        filter_mode = "host";
        filter_mode_shell_up_key_binding = "host";
        style = "compact";
        inline_height = 30;
        max_preview_height = 20;
        invert = true;
        show_tabs = false;
        enter_accept = true;
      };
    };
  };

  home.username = lib.mkDefault metaConfig.username;
  home.homeDirectory = lib.mkDefault "/home/${metaConfig.username}";

  # == File Management Helpers ==
  services.udiskie.enable = true; # (목적: USB 자동 마운트 및 트레이 알림)

  home.packages = with pkgs; [
    trash-cli # (목적: 터미널용 휴지통 관리 도구)
  ];

  home.shellAliases = {
    # == Trash-cli Shortcuts ==
    tp = "trash-put"; # (목적: 파일을 휴지통으로 이동)
    tl = "trash-list"; # (목적: 휴지통 목록 확인)
    tr = "trash-restore"; # (목적: 휴지통 파일 복구)
    te = "trash-empty"; # (목적: 휴지통 비우기)
  };

  # (주의: Home Manager 최초 설치 시점의 호환성 지표)
  home.stateVersion = metaConfig.stateVersion;
}
