{mkModHere, ...}: let
  base = mkModHere __curPos null ({
    config,
    lib,
    ...
  }: {
    hm = {
      programs = {
        home-manager.enable = true;
        gh = {
          enable = true;
          settings = {
            git_protocol = "ssh";
          };
        }; # (목적: GitHub CLI — devel/gui 여부와 무관하게 기본 제공)
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

      # (주의: Home Manager 최초 설치 시점의 호환성 지표)
      home.stateVersion = config.workspace.stateVersion;
    };
  });
in {
  imports =
    base.imports
    ++ [
      ./home/atuin.nix
      ./home/zsh.nix
    ];
}
