/*
  services.tailpass-authagent — deploy/tailpass-authagent.service + deploy/install-authagent.sh를
  NixOS 옵션으로 대체한다. D-Bus 시스템 버스 정책(deploy/nix/dbus-policy.nix)은
  services.dbus.packages로 자동 등록되고, App 자신의 unlock polkit action
  (it.bitstep.tailpass.policy)은 tailpass-app 파생물에 이미 포함되어 있어
  environment.systemPackages에 넣기만 하면 polkit이 자동 스캔한다.

  it.bitstep.tailpass.daemon-setup.policy(계정 설치용 pkexec 트리거)는 의도적으로
  설치하지 않는다 — NixOS 모듈이 계정을 선언적으로 만들므로 이 action이 트리거하는
  install-daemon-account.sh 자체가 NixOS 배포에 존재하지 않는다.
*/
{ config, lib, pkgs, tailpassPackage, ... }:

let
  cfg = config.services.tailpass-authagent;
  dbusPolicy = pkgs.callPackage ../dbus-policy.nix { tailpassPackage = cfg.package; };
in
{
  options.services.tailpass-authagent = {
    enable = lib.mkEnableOption "Tailpass authagent (TPM authValue/keyring bio_key를 독점 보유하는 D-Bus 서비스)";

    package = lib.mkOption {
      type = lib.types.package;
      default = tailpassPackage;
      description = "tailpass-authagent 바이너리를 담은 패키지 (기본값: deploy/nix/package.nix의 tailpass-app 재포장 파생물)";
    };
  };

  config = lib.mkIf cfg.enable {
    users.users.tailpass-auth = {
      isSystemUser = true;
      group = "tailpass-auth";
      home = "/var/lib/tailpass-auth";
      createHome = false; # systemd StateDirectory가 소유권까지 맞춰 생성
      # TPM 리소스 매니저(/dev/tpmrm0) 접근용 — security.tpm2.enable일 때만 tss 그룹이 존재.
      extraGroups = lib.optional config.security.tpm2.enable "tss";
    };
    users.groups.tailpass-auth = { };

    services.dbus.packages = [ dbusPolicy ];

    # App 자신의 unlock 세리모니 polkit action(it.bitstep.tailpass.policy)이 이 패키지 안에
    # 들어있어 자동 등록된다 — daemon/authagent를 헤드리스로 설치하는 경우에도 필요하므로
    # authagent 모듈에서 함께 넣는다(daemon.nix에는 App 패키지 자체를 넣지 않음).
    environment.systemPackages = [ cfg.package ];

    systemd.services.tailpass-authagent = {
      description = "Tailpass authagent (privileged D-Bus secret broker for TPM/keyring biometric unlock)";
      wantedBy = [ "multi-user.target" ];

      serviceConfig = {
        Type = "dbus";
        BusName = "it.bitstep.tailpass.AuthAgent1";
        User = "tailpass-auth";
        Group = "tailpass-auth";
        ExecStart = "${cfg.package}/bin/tailpass-authagent";
        Restart = "on-failure";
        RestartSec = 3;

        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        StateDirectory = "tailpass-auth";
        LimitCORE = 0;
      };
    };
  };
}
