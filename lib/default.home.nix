{ pkgs, metaConfig, ... }: {
  programs = {
    home-manager.enable = true;
  };

  # 이 버전은 Home Manager가 처음 설치된 시점의 상태를 정의합니다.
  # 업데이트 시 이 값을 굳이 바꿀 필요는 없으며, 호환성을 위한 지표입니다.
  home.stateVersion = metaConfig.stateVersion;
}
