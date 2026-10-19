# 사용 모드(posture) 허브 — 노트북의 사용 상태(힌지 각도 → laptop/tent/tablet, 화면 방향, 덮개 열림/닫힘)를 한 곳에서 읽고 발행한다.
# 모든 노트북(type = "laptop")에 적용된다: 덮개는 모든 노트북이 갖고, 힌지/가속도 센서는 있을 때만 쓴다(2-in-1 전용 기능은 host.toml `convertible = true` 호스트에만: vkb.nix, display-manager.nix 의 회전, core.touch.nix).
#
#   [센서] → posture-daemon(root, 이 파일의 system 서비스) → /run/posture/state.json → 경로 유닛 → 소비자들(posture-apply)
#                                                          └ /run/posture/telemetry.json (힌지 각도: 자주 바뀌지만 소비자를 깨우지 않음)
#
# 설계 원칙(유지보수/버그 최소화):
#  - 센서는 한 프로세스만 읽고 값을 한 번만 해석한다(경계값/디바운스는 mods/_data/posture/posture_daemon.py 한 곳).
#  - 상태는 하나의 스냅샷(JSON, 원자적 교체)이고 **변할 때만** 갱신한다. 가져가기는 `posture get mode|lid|rotation|angle`, 알림은 state.json 변경을 보는 경로 유닛.
#  - 소비자는 "수준 기반 + 멱등" 조정기: 이벤트를 놓쳐도 아무 때나 실행하면 현재 상태에 맞춰짐(로그인/reload 때도 같은 코드).
#  - 안전한 기본값(서비스 정지/파일 없음 → laptop, 덮개 열림)은 `posture` CLI 한 곳에서 처리 → 키보드가 꺼지거나 화면이 꺼진 채 남지 않음.
#  - 소비자는 `posture.consumers` 옵션에 명령을 한 줄 추가하면 연결된다(덮개/입력 정책: core.bind.hwctl.nix, 가상 키보드: vkb.nix, 화면 회전: display-manager.nix).
#    이 파일은 허브(센서 → 상태 → 소비자 호출)만 담당하고 소비자의 내용은 모른다.
#  - 안전과 직결된 동작(덮개를 닫으면 잠금)은 허브를 거치지 않고 Hyprland 바인딩에 둔다: 허브가 죽어도 잠겨야 한다.
# 힌지 센서도 덮개 스위치도 없는 기기에서는 posture-daemon 이 바로 종료하고 CLI 는 안전한 기본값을 돌려준다.
{
  mkPartOf,
  lib,
  ...
}: let
  base = mkPartOf "mods.gui" ({
    pkgs,
    lib,
    config,
    ...
  }: let
    isLaptop = config.workspace.type == "laptop";
    postureCli = pkgs.writeShellScriptBin "posture" ''
      exec ${pkgs.python3}/bin/python3 -I ${../../_data/posture/posture} "$@"
    '';
    # 소비자들을 차례로 실행. 하나가 실패해도 나머지는 실행하고 기록만 남김(소비자끼리 서로 영향 없음)
    # **실행 도중 상태가 바뀌면 다시 돈다**: 경로 유닛은 이미 실행 중인 서비스를 다시 시작하지 못해서(start 요청이 무시됨) 그 변경을 놓친다.
    # (실측 2026-10-19: 덮개를 닫고 1초 안에 열면 닫힘 처리 중에 온 열림이 유실돼 백라이트가 0 인 채 남았다.) 시작 때와 끝날 때의 `posture sig`
    # (모드/덮개/회전/눕힘; 각도는 제외)가 같아질 때까지 반복한다(최대 5회). 소비자는 멱등이라 다시 돌려도 안전하다.
    cfg = config.posture;
    applyAll = pkgs.writeShellScriptBin "posture-apply" ''
      for pass in 1 2 3 4 5; do
        before=$(${postureCli}/bin/posture sig)
        ${lib.concatMapStrings (c: ''
          ${c} || ${pkgs.util-linux}/bin/logger -t posture-apply "소비자 실패: ${c}"
        '')
        cfg.consumers}
        after=$(${postureCli}/bin/posture sig)
        [ "$before" = "$after" ] && break
        ${pkgs.util-linux}/bin/logger -t posture-apply "실행 중 상태가 바뀜($before → $after): 다시 적용($pass)"
      done
      ${pkgs.util-linux}/bin/logger -t posture-apply "applied: $(${postureCli}/bin/posture get mode) lid=$(${postureCli}/bin/posture get lid)"
    '';
  in {
    os = lib.mkIf isLaptop {
      systemd.services.posture-daemon = {
        # (부팅 콘솔은 한글이 네모로 보이므로 영어: 사용 모드(힌지 각도 → laptop/tent/tablet) 판정과 발행)
        description = "Posture hub: hinge angle to laptop/tent/tablet";
        wantedBy = ["multi-user.target"];
        serviceConfig = {
          ExecStart = "${pkgs.python3}/bin/python3 -I ${../../_data/posture/posture_daemon.py}";
          Restart = "on-failure";
          RestartSec = 5;
          RuntimeDirectory = "posture";
          RuntimeDirectoryMode = "0755";
          RuntimeDirectoryPreserve = "yes";
          ProtectHome = true;
          PrivateTmp = true;
          NoNewPrivileges = true;
        };
      };
    };

    hm = lib.mkIf isLaptop {
      home.packages = [postureCli applyAll];
      posture.cli = postureCli;

      # 상태 파일이 바뀌면 소비자를 한 번 실행. 서비스가 정지할 때도 안전한 값(laptop)이 발행되므로 같은 경로로 복원됨
      systemd.user.paths.posture-apply = {
        Unit.Description = "사용 모드 상태 변경 감시";
        Path = {
          PathChanged = "/run/posture/state.json";
          Unit = "posture-apply.service";
        };
        Install.WantedBy = ["default.target"];
      };
      systemd.user.services.posture-apply = {
        Unit = {
          Description = "사용 모드 소비자 실행 (입력 장치 정책 등)";
          StartLimitIntervalSec = 0; # 힌지를 빠르게 움직여도 경로 유닛의 시작 제한에 걸리지 않게
        };
        Service = {
          Type = "oneshot";
          ExecStart = "${applyAll}/bin/posture-apply";
        };
      };

      # 로그인과 설정 reload 때도 같은 소비자를 다시 실행(Hyprland 는 시작/reload 때 장치 상태를 초기화함)
      wayland.windowManager.hyprland.extraConfig = ''
        hl.on("hyprland.start", function()
          hl.exec_cmd("sleep 1; ${applyAll}/bin/posture-apply")
        end)
        hl.on("config.reloaded", function()
          hl.exec_cmd("${applyAll}/bin/posture-apply")
        end)
      '';
    };
  });
in {
  inherit (base) imports;

  # (주의: options 는 mkIf 로 감쌀 수 없으므로 항상 선언)
  options.posture.cli = lib.mkOption {
    type = lib.types.package;
    internal = true;
    description = "posture CLI 패키지(소비자 스크립트가 `posture get mode` 등으로 현재 사용 모드를 읽을 때 씀).";
  };
  options.posture.consumers = lib.mkOption {
    type = lib.types.listOf lib.types.str;
    default = [];
    description = "사용 모드가 바뀔 때(그리고 로그인/reload 때) 차례로 실행할 명령. 멱등이어야 하고 `posture get mode` 등으로 현재 값을 읽는다.";
  };
}
