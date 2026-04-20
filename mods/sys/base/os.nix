{
  pkgs,
  lib,
  config,
  ...
}: {
  imports = [
    ./os/_optimize.nix
    ./os/_server-optimize.nix
    ./os/_boot.nix
    ./os/_disk.nix
    ./os/_swap.nix
    ./os/_power.nix
  ];

  # == User & Nix Engine ==
  users.users.${config.workspace.username} = {
    isNormalUser = true;
    extraGroups = ["wheel"];
    # (참고: networkmanager 그룹은 mods.sys.services.networkmanager.nix에서 추가됨)
    shell = pkgs.zsh;
  };

  # (목적: root 포함 모든 계정에 Zsh 적용; 상세 설정은 Home Manager에서 처리)
  users.defaultUserShell = pkgs.zsh;
  programs.zsh.enable = true;

  # (목적: nix.channel.enable = false 이후 남은 레거시 채널 디렉터리 정리)
  # (이유: channel.enable = false가 새 경로 생성은 막지만 기존 디렉터리는 제거하지 않음)
  system.activationScripts.removeOldChannels = {
    text = ''
      rm -rf /root/.nix-defexpr/channels
      rm -rf /nix/var/nix/profiles/per-user/root/channels
      rm -rf /home/${config.workspace.username}/.nix-defexpr/channels
      rm -rf /nix/var/nix/profiles/per-user/${config.workspace.username}/channels
    '';
    deps = ["users"];
  };

  nix = {
    # (목적: 채널 관리 비활성화 → 레거시 채널 경로 warning 제거)
    channel.enable = false;
    # (목적: 일반 nix-shell 사용 시 <nixpkgs> 참조 보장 — 새 세션부터 NIX_PATH로 주입)
    # (nixup 스크립트 자체는 shebang의 -I 플래그로 세션 무관하게 직접 해결)
    nixPath = ["nixpkgs=flake:nixpkgs"];

    settings = {
      auto-optimise-store = true; # (목적: 중복 파일 자동 하드링크)
      max-jobs = "auto";
      trusted-users = ["root" "@wheel"];
      experimental-features = ["nix-command" "flakes"];
    };

    gc = {
      # (목적: 7일 이상 된 이전 세대 자동 정리)
      automatic = true;
      dates = "weekly";
      options = "--delete-older-than 7d";
    };
  };

  # (목적: x86_64 호스트에서 aarch64 크로스 빌드 지원.
  #         QEMU binfmt_misc 커널 등록 및 nix.settings.extra-platforms 자동 추가.)
  boot.binfmt.emulatedSystems = lib.mkIf (pkgs.stdenv.hostPlatform.system == "x86_64-linux") [
    "aarch64-linux"
  ];

  # == Networking & Localization ==
  # (참고: networkmanager.enable은 mods.sys.services.networkmanager.nix에서 처리)
  networking.hostName = config.workspace.hostname;

  time.timeZone = config.workspace.timeZone;
  i18n.defaultLocale = config.workspace.defaultLocale;
  i18n.supportedLocales =
    ["${config.workspace.defaultLocale}/UTF-8"]
    ++ lib.optional (config.workspace.extraLocale != null)
    "${config.workspace.extraLocale}/UTF-8";

  environment.systemPackages = with pkgs; [
    git
    nano
    wget
    curl
    htop
  ];

  system.stateVersion = config.workspace.stateVersion;
}
