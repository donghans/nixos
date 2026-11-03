# 데스크톱(beelink-ser7-co)의 incus VM `qa-desktop` 화면을 이 머신에서 본다 — 랩탑 전용(호스트 toml 의 `qa-desktop-view = true`).
# incus 클라이언트가 데스크톱의 로컬 소켓(/var/lib/incus/unix.socket)에 SSH 포워딩으로 붙어 `incus console --type=vga`(SPICE)를 연다.
# 터널은 뷰어가 떠 있는 동안만 유지하고, 창을 닫으면(뷰어 종료) trap 이 터널과 소켓을 정리한다.
# SPICE 콘솔은 한 번에 한 곳에서만 연결되므로 데스크톱에서 이미 보고 있으면 "already connected" 로 거절된다
# (강제로 가져오면 그쪽 뷰어가 끊기니 자동으로 하지 않는다).
{mkMod, ...}:
mkMod __curPos "QA 데스크톱(원격 incus VM) 화면 보기" ({pkgs, ...}: let
  remoteHost = "beelink-ser7-co";
  vm = "qa-desktop";
  viewScript = pkgs.writeShellScriptBin "qa-desktop-view" ''
    sock="''${XDG_RUNTIME_DIR:-/tmp}/incus-${remoteHost}.sock"
    rm -f "$sock"

    ${pkgs.openssh}/bin/ssh -o BatchMode=yes -o ExitOnForwardFailure=yes -N \
      -L "$sock:/var/lib/incus/unix.socket" ${remoteHost} &
    tunnel=$!
    trap 'kill "$tunnel" 2>/dev/null; rm -f "$sock"' EXIT

    # 소켓이 생길 때까지 최대 10초 대기(터널이 죽었으면 바로 포기)
    for _ in $(seq 1 50); do
      [ -S "$sock" ] && break
      kill -0 "$tunnel" 2>/dev/null || break
      sleep 0.2
    done
    if [ ! -S "$sock" ]; then
      ${pkgs.libnotify}/bin/notify-send "QA 데스크톱" "${remoteHost} 에 SSH 터널을 열지 못했습니다"
      exit 1
    fi

    # 뷰어가 끝날 때까지 포그라운드로 기다린다. 실패 사유(이미 연결됨 등)는 알림으로 보인다.
    if ! out=$(INCUS_SOCKET="$sock" PATH="${pkgs.virt-viewer}/bin:$PATH" \
        ${pkgs.incus}/bin/incus console --type=vga ${vm} 2>&1); then
      ${pkgs.libnotify}/bin/notify-send "QA 데스크톱" "$(printf '%s' "$out" | grep -m1 '^Error' || echo '화면을 열지 못했습니다')"
      exit 1
    fi
  '';

  viewDesktop = pkgs.makeDesktopItem {
    name = "qa-desktop-view";
    desktopName = "QA 데스크톱 (원격)";
    exec = "${viewScript}/bin/qa-desktop-view";
    icon = "virt-manager";
    comment = "${remoteHost} 의 incus VM ${vm} 화면 보기(창을 닫으면 SSH 터널도 닫힘)";
    categories = ["System" "Emulator"];
    terminal = false;
  };
in {
  os = {
    environment.systemPackages = [viewScript viewDesktop];
  };
})
