# [working-refactor] 해당 구문은 before-refactor/lib/_base/default.home.nix 에 있었음
# [working-refactor] 해당 구문은 after-refactor/... 로 들어가야 함
{
  pkgs,
  lib,
  config,
  ...
}: {
  # [working-refactor] 해당 파일은 실제 /tmp/nixos-build/<경로> 로 이동 후 nhw에 의해 임시 경로에서 실행됩니다.
  imports = [
    ./home/atuin.nix
    ./home/zsh.nix
  ];

  programs = {
    home-manager.enable = true;
    git = {
      enable = true;
      settings = {
        user.name = config.workspace.gitName;
        user.email = config.workspace.gitEmail;
        url."git@github.com:".insteadOf = "https://github.com/";
      };
    };
  };

  home.username = lib.mkDefault config.workspace.username;
  home.homeDirectory = lib.mkDefault (
    if config.workspace.username == "root"
    then "/root"
    else "/home/${config.workspace.username}"
  );

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
  home.stateVersion = config.workspace.stateVersion;
}
