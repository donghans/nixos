{mkMod, ...}:
mkMod __curPos "Incus VM" ({
  cfg,
  config,
  pkgs,
  lib,
  ...
}: let
  # GUI VM 목록을 fuzzel로 선택 → 상태에 따라 켜기/끄기/뷰어 열기 액션 선택
  spiceViewerScript = pkgs.writeShellScriptBin "incus-vm" ''
    # 가상머신(컨테이너 제외)만 조회 - "이름 (상태)" 형식으로 표시
    entries=$(${pkgs.incus}/bin/incus list --format=json 2>/dev/null \
      | ${pkgs.jq}/bin/jq -r '.[] | select((.type | ascii_downcase) == "virtual-machine") | "\(.name) (\(.status))"')

    if [ -z "$entries" ]; then
      ${pkgs.libnotify}/bin/notify-send "Incus" "등록된 VM이 없습니다"
      exit 1
    fi

    # 1단계: VM 선택
    selected=$(printf '%s\n' "$entries" \
      | ${pkgs.fuzzel}/bin/fuzzel --dmenu --prompt="VM 선택 > ")
    [ -z "$selected" ] && exit

    vm_name=$(echo "$selected" | awk '{print $1}')
    vm_status=$(echo "$selected" | grep -oP '\(\K[^)]+')

    # 2단계: 상태에 따라 가능한 액션만 표시
    if [ "$vm_status" = "Running" ]; then
      actions="터미널 열기\n뷰어 열기\n끄기\n강제 종료\n재시작"
    else
      actions="켜기\n켜고 터미널 열기\n켜고 뷰어 열기"
    fi

    action=$(printf "$actions" \
      | ${pkgs.fuzzel}/bin/fuzzel --dmenu --prompt="$vm_name > ")
    [ -z "$action" ] && exit

    case "$action" in
      "터미널 열기")
        ${pkgs.kitty}/bin/kitty --title "incus: $vm_name" \
          ${pkgs.incus}/bin/incus console "$vm_name" &
        ;;
      "켜기")
        ${pkgs.incus}/bin/incus start "$vm_name"
        ;;
      "켜고 터미널 열기")
        ${pkgs.libnotify}/bin/notify-send "Incus" "$vm_name 시작 중..."
        ${pkgs.incus}/bin/incus start "$vm_name" && \
          ${pkgs.kitty}/bin/kitty --title "incus: $vm_name" \
            ${pkgs.incus}/bin/incus console "$vm_name" &
        ;;
      "켜고 뷰어 열기")
        ${pkgs.libnotify}/bin/notify-send "Incus" "$vm_name 시작 중..."
        ${pkgs.incus}/bin/incus start "$vm_name" && \
          PATH="${pkgs.virt-viewer}/bin:$PATH" \
          ${pkgs.incus}/bin/incus console --type=vga "$vm_name" &
        ;;
      "뷰어 열기")
        PATH="${pkgs.virt-viewer}/bin:$PATH" \
        ${pkgs.incus}/bin/incus console --type=vga "$vm_name" &
        ;;
      "끄기")
        ${pkgs.incus}/bin/incus stop "$vm_name"
        ;;
      "강제 종료")
        ${pkgs.incus}/bin/incus stop --force "$vm_name"
        ;;
      "재시작")
        ${pkgs.incus}/bin/incus restart "$vm_name"
        ;;
    esac
  '';

  spiceViewerDesktop = pkgs.makeDesktopItem {
    name = "incus-vm";
    desktopName = "Incus VM";
    exec = "${spiceViewerScript}/bin/incus-vm";
    icon = "virt-manager";
    comment = "Incus VM 시작·종료·뷰어 연결";
    categories = ["System" "Emulator"];
    terminal = false;
  };
in {
  os = {
    assertions = [
      {
        assertion = config.mods.sys.services.incus.enable;
        message = "mods.gui.apps.incus-vm는 mods.sys.services.incus.enable = true 가 필요합니다";
      }
    ];
    environment.systemPackages = [spiceViewerScript spiceViewerDesktop];
  };
})
