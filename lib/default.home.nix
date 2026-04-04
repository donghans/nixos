{
  lib,
  metaConfig,
  ...
}: {
  programs = {
    home-manager.enable = true;
  };

  home.username = lib.mkDefault metaConfig.username;
  home.homeDirectory = lib.mkDefault "/home/${metaConfig.username}";

  # (주의: Home Manager 최초 설치 시점의 호환성 지표)
  home.stateVersion = metaConfig.stateVersion;
}
