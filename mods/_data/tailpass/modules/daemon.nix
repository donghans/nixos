/*
  services.tailpass-daemon — deploy/tailpass-daemon.service + deploy/install-daemon-account.sh를
  NixOS 옵션으로 선언적으로 대체한다(로드맵: NixOS는 셸 스크립트로 전용 계정을 만들거나
  /etc/systemd/system에 유닛을 심는 방식 자체를 근본적으로 지원하지 않음).

  clients/daemon/src/paths.rs::ipc_path()는 systemd $RUNTIME_DIRECTORY를 최우선으로 쓰고
  영속 상태 디렉터리를 요구하지 않으므로(재확인 완료), 이 모듈은 RuntimeDirectory만
  선언하고 StateDirectory는 두지 않는다.
*/
{ config, lib, pkgs, tailpassPackage, ... }:

let
  cfg = config.services.tailpass-daemon;
in
{
  options.services.tailpass-daemon = {
    enable = lib.mkEnableOption "Tailpass daemon (전용 미권한 계정으로 도는 IPC 데몬)";

    package = lib.mkOption {
      type = lib.types.package;
      default = tailpassPackage;
      description = "tailpass-daemon 바이너리를 담은 패키지 (기본값: deploy/nix/package.nix의 tailpass-app 재포장 파생물)";
    };

    users = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
      example = [ "alice" ];
      description = ''
        daemon IPC 소켓(root:tailpass-daemon 0770)에 접근할 로그인 사용자 목록.
        여기 나열된 사용자만 tailpass-daemon 그룹에 편입된다(opt-in) — 전역 자동 편입은
        하지 않는다.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    users.users = {
      tailpass-daemon = {
        isSystemUser = true;
        group = "tailpass-daemon";
        home = "/var/lib/tailpass-daemon";
        createHome = true;
      };
    } // lib.genAttrs cfg.users (name: {
      extraGroups = [ "tailpass-daemon" ];
    });
    users.groups.tailpass-daemon = { };

    systemd.services.tailpass-daemon = {
      description = "Tailpass daemon (dedicated unprivileged account)";
      wantedBy = [ "multi-user.target" ];

      serviceConfig = {
        Type = "simple";
        User = "tailpass-daemon";
        Group = "tailpass-daemon";
        ExecStart = "${cfg.package}/bin/tailpass-daemon";
        Restart = "on-failure";
        RestartSec = 3;
        # 로그인 사용자는 tailpass-daemon 그룹에 있어야 이 소켓에 접근 가능
        # (clients/daemon/src/server.rs::peer_is_authorized()).
        RuntimeDirectory = "tailpass";
        RuntimeDirectoryMode = "0770";
        # pinMaterial이 코어 덤프에 포함되지 않도록 (deploy/tailpass-daemon.service와 동일 취지).
        PrivateTmp = true;
        NoNewPrivileges = true;
        LimitCORE = 0;
      };
    };
  };
}
