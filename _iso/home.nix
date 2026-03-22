{ pkgs, metaConfig, ... }: {
  imports = [ ./lib/hyprland.home.nix ];

  home.packages = with pkgs; [
    zed-editor
  ];

  # ISO 터미널에서 편하게 쓸 설정들
  # programs.bash.shellAliases = {
  #   # 실제 설치 시 편하게 쓰기 위한 예시 코드
  #   install-my-os = "nixos-install --flake .#beelink-ser7-co";
  # };
}
