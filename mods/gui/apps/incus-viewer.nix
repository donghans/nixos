{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.gui.apps."incus-viewer";

  # 실행 중인 Incus VM 목록을 fuzzel로 선택해 remote-viewer(SPICE)로 연결
  spiceViewerScript = pkgs.writeShellScriptBin "incus-spice-viewer" ''
    instances=$(${pkgs.incus}/bin/incus list --format=json 2>/dev/null \
      | ${pkgs.jq}/bin/jq -r '.[] | select(.status=="Running") | .name' \
      | while IFS= read -r name; do
          [ -S "/run/incus/$name/qemu.spice" ] && echo "$name"
        done)

    if [ -z "$instances" ]; then
      ${pkgs.libnotify}/bin/notify-send "Incus SPICE Viewer" "실행 중인 VM이 없습니다"
      exit 1
    fi

    selected=$(printf '%s\n' "$instances" \
      | ${pkgs.fuzzel}/bin/fuzzel --dmenu --prompt="VM 선택 > ")
    [ -n "$selected" ] && \
      ${pkgs.virt-viewer}/bin/remote-viewer \
        "spice+unix:///run/incus/$selected/qemu.spice" &
  '';

  spiceViewerDesktop = pkgs.makeDesktopItem {
    name = "incus-spice-viewer";
    desktopName = "Incus SPICE Viewer";
    exec = "${spiceViewerScript}/bin/incus-spice-viewer";
    icon = "computer-vm";
    comment = "Incus VM에 SPICE 클라이언트로 연결";
    categories = ["System" "Emulator"];
    terminal = false;
  };
in
{options.mods.gui.apps."incus-viewer".enable = mkEnableOption "Incus SPICE Viewer";}
// (
  if isNixOS
  then {
    config = mkIf cfg.enable {
      assertions = [
        {
          assertion = config.mods.sys.services.incus.enable;
          message = "mods.gui.apps.incus-viewer는 mods.sys.services.incus.enable = true 가 필요합니다";
        }
      ];
      environment.systemPackages = [spiceViewerScript spiceViewerDesktop];
    };
  }
  else {}
)
