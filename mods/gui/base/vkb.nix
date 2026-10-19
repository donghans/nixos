# 가상 키보드(wvkbd) + 제어 CLI(vkb) — 자세 허브(core.posture.nix)의 소비자.
#  - 숨긴 채 상시 대기하는 wvkbd 를 사용자 서비스로 띄우고, 시작 인자(높이/폭/글자 크기/모드/레이어)는 `vkb args` 가 화면 물리 크기(mm→px)로 계산한다.
#  - 보이기/숨기기/크기/모드는 `vkb` 명령이 시그널·재시작으로 제어한다(wvkbd 는 높이를 시작할 때만 받음 — mods/_data/vkb/vkb.py 머리말 참고).
#  - 텐트/태블릿에서 자동으로 보이고 노트북 모드에서 숨기는 것은 `vkb apply-posture` 를 자세 허브 소비자로 등록해서 한다.
#  - wvkbd 패치(플로팅 모드, 표준 PC 배열, 한/영·Sup 키)는 mods/_data/wvkbd/ (README 참고).
#  - waybar 버튼은 waybar.nix 가 `vkb waybar ...` 명령을 호출한다.
{mkPartOf, ...}:
mkPartOf "mods.gui" ({
  pkgs,
  lib,
  config,
  ...
}: let
  isLaptop = config.workspace.type == "laptop";
  wvkbd = pkgs.wvkbd.overrideAttrs (old: {
    # 적용 순서 중요: pc-layout 은 float-mode 가 만든 Float 키 종류를 쓴다
    patches = (old.patches or []) ++ [../../_data/wvkbd/float-mode.patch ../../_data/wvkbd/pc-layout.patch];
  });
  vkbCli = pkgs.writeShellScriptBin "vkb" ''
    export VKB_POSTURE=${config.posture.cli}/bin/posture
    exec ${pkgs.python3}/bin/python3 -I ${../../_data/vkb/vkb.py} "$@"
  '';
  wvkbdStart = pkgs.writeShellScript "wvkbd-start" ''
    mapfile -t args < <(${vkbCli}/bin/vkb args) || true
    [ "''${#args[@]}" -gt 0 ] || args=(-H 450 -L 380 --hidden)
    exec ${wvkbd}/bin/wvkbd-mobintl "''${args[@]}" --on-mode "${vkbCli}/bin/vkb mode-changed"
  '';
in {
  hm = lib.mkIf isLaptop {
    home.packages = [vkbCli];
    posture.consumers = ["${vkbCli}/bin/vkb apply-posture"];

    # 숨긴 채 상시 대기(메모리만 차지, 시그널로 즉시 표시)
    systemd.user.services.wvkbd = {
      Unit = {
        Description = "가상 키보드 wvkbd (숨김 상태로 대기, vkb 명령으로 제어)";
        After = ["graphical-session.target"];
        PartOf = ["graphical-session.target"];
      };
      Service = {
        ExecStart = "${wvkbdStart}";
        Restart = "on-failure";
      };
      Install.WantedBy = ["graphical-session.target"];
    };
  };
})
