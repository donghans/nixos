{
  lib,
  config,
  isNixOS ? false,
  ...
}: let
  inherit (import ./_lib.nix {inherit lib;}) importDir;
in {
  imports =
    # gui/core: fcitx/polkit/xdg는 컨텍스트 무관, os/home은 isNixOS 분기
    # (Phase 3에서 mkPartOf 전환 완료 후 조건 제거 예정)
    [
      ./gui/core/fcitx.nix
      ./gui/core/polkit.nix
      ./gui/core/xdg.nix
    ]
    ++ (
      if isNixOS
      then [./gui/core/os.nix ./gui/core/greeter.nix]
      else [./gui/core/home.nix]
    )
    ++ importDir ./gui/apps
    ++ importDir ./gui/utils;

  options.mods.gui.enable = lib.mkEnableOption "GUI Bundle (Hyprland, Waybar, etc)";

  # == gui.enable 마스터 스위치: 하위 항목 기본값 활성화 ==
  # (사용자는 개별 항목을 `lib.mkForce false`로 비활성화 가능)
  config = lib.mkIf config.mods.gui.enable {
    mods.sys.fonts.enable = true;
    mods.sys.vfs.enable = true;
    mods.gui.apps.vivaldi.enable = lib.mkDefault true;
    mods.gui.apps.slack.enable = lib.mkDefault true;
    mods.gui.apps.bitwarden.enable = lib.mkDefault true;
    mods.gui.apps.speedcrunch.enable = lib.mkDefault true;
    mods.gui.utils.custom-notify-logger.enable = lib.mkDefault true;
    mods.gui.apps."incus-vm".enable = lib.mkDefault true;
  };
}
