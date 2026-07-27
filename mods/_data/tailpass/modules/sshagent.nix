/*
  services.tailpass-sshagent — deploy/tailpass-sshagent.service(비-Nix 배포용
  systemd `--user` 유닛 파일)를 NixOS `systemd.user.services` 옵션으로
  대체한다. daemon/authagent와 달리 전용 계정이 없는 **로그인 사용자 세션
  상주 프로세스**다(SSH_AUTH_SOCK은 그 사용자 세션에서만 의미가 있으므로) —
  그래서 `systemd.services`(시스템 유닛)가 아니라 `systemd.user.services`
  (사용자 유닛)로 선언한다. 로드맵 `ssh-agent-ondemand.md` Plan 1 참고.

  **opt-in 지점은 `services.tailpass-sshagent.enable`뿐이다 — daemon.nix/
  authagent.nix와 동일한 원칙**: `wantedBy = [ "default.target" ]`을 넣어야
  `systemd.user.services`가 `[Install]` 섹션을 실제로 생성한다 — 이걸 비워두면
  `systemctl --user enable`이 "설치 설정(Install=)이 없다"는 오류로 아예
  실패해버린다(초안에서 opt-in을 이중으로 만들려고 `wantedBy`를 비웠다가
  `nix flake check`로 생성된 유닛을 직접 열어보고 이 버그를 발견해 고쳤다 —
  daemon/authagent와 다른 이중 게이트를 만들 이유가 없었다). 따라서 이
  모듈은 daemon/authagent와 완전히 같은 방식으로 동작한다: NixOS 시스템
  설정에 `services.tailpass-sshagent.enable = true;`라고 **명시적으로 쓰는
  행위 자체**가 opt-in 체크포인트이고, 그 이후엔 이 머신에 로그인하는 모든
  사용자 세션에서 자동 시작된다(daemon이 시스템 전체에 한 번 뜨는 것과
  같은 급의 결정 — "특정 사용자만" 세분화하려면 home-manager 영역의
  `home-manager.users.<name>.systemd.user.services`가 필요하며, 이 모듈은
  거기까지는 다루지 않는다).

  활성화하려면 NixOS 시스템 설정(flake 기준)에 다음을 추가한다:

    imports = [ tailpass.nixosModules.default ];
    services.tailpass-sshagent.enable = true;

  (이미 열려 있던 셸에는 재로그인 후에만 SSH_AUTH_SOCK이 반영된다 —
  deploy/tailpass-sshagent.service와 동일한 일반적 환경변수 전파 제약.)
*/
{ config, lib, pkgs, tailpassPackage, ... }:

let
  cfg = config.services.tailpass-sshagent;
in
{
  options.services.tailpass-sshagent = {
    enable = lib.mkEnableOption "Tailpass on-demand SSH agent 사이드카 (1Password SSH Agent식 서명 승인, 활성화 시 모든 로그인 사용자 세션에 적용)";

    package = lib.mkOption {
      type = lib.types.package;
      default = tailpassPackage;
      description = "tailpass-sshagent 바이너리를 담은 패키지 (기본값: deploy/nix/package.nix의 tailpass-app 재포장 파생물)";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.user.services.tailpass-sshagent = {
      description = "Tailpass on-demand SSH agent (roadmap ssh-agent-ondemand Plan 1)";
      # daemon.nix/authagent.nix와 동일하게 `cfg.enable` 자체가 opt-in
      # 체크포인트다 — 여기서 wantedBy를 비우면 [Install] 섹션이 안 생겨
      # `systemctl --user enable`이 실패한다(위 주석 참고).
      wantedBy = [ "default.target" ];

      serviceConfig = {
        Type = "simple";
        ExecStart = "${cfg.package}/bin/tailpass-sshagent";
        # SSH_AUTH_SOCK을 이후 --user 세션에서 스폰되는 프로세스(새 셸/터미널)에
        # 전파한다 — deploy/tailpass-sshagent.service의 ExecStartPost와 동일한
        # 로직, 경로만 Nix store 절대경로로 치환.
        ExecStartPost = ''${pkgs.bash}/bin/sh -c '${pkgs.systemd}/bin/systemctl --user set-environment SSH_AUTH_SOCK=%t/tailpass-ssh-agent.sock; ${pkgs.dbus}/bin/dbus-update-activation-environment --systemd SSH_AUTH_SOCK 2>/dev/null || true' '';
        Restart = "on-failure";
        RestartSec = 3;
        NoNewPrivileges = true;
        LimitCORE = 0;
      };
    };
  };
}
