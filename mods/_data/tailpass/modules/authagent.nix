/*
  services.tailpass-authagent — deploy/tailpass-authagent.service + deploy/install-authagent.sh를
  NixOS 옵션으로 대체한다. D-Bus 시스템 버스 정책(deploy/nix/dbus-policy.nix)은
  services.dbus.packages로 자동 등록되고, App 자신의 unlock polkit action
  (it.bitstep.tailpass.policy)은 tailpass-app 파생물에 이미 포함되어 있어
  environment.systemPackages에 넣기만 하면 polkit이 자동 스캔한다.

  it.bitstep.tailpass.daemon-setup.policy(계정 설치용 pkexec 트리거)는 의도적으로
  설치하지 않는다 — NixOS 모듈이 계정을 선언적으로 만들므로 이 action이 트리거하는
  install-daemon-account.sh 자체가 NixOS 배포에 존재하지 않는다.

  **왜 `enable` 기본값이 false인가(opt-in) — 정책 회귀 아님**: `.deb`/`.rpm`/AppImage는
  "패키지 설치 자체가 이미 root 승인"이라는 전제로 postinst/pkexec가 daemon 전용
  계정·authagent를 자동 설치하도록 정책이 바뀌었다(로드맵 client-security-hardening.md
  E/F절). 이 전제는 NixOS에는 성립하지 않는다 — `imports`에 모듈을 넣는 것과
  서비스를 실제로 활성화(`services.X.enable = true`)하는 것이 완전히 분리된 별개
  행위이기 때문이다(합성 가능성 원칙). 그래서 NixOS만 다른 서비스 모듈(daemon.nix
  포함)과 동일하게 `lib.mkEnableOption` 관용구(기본 false)를 그대로 따른다 —
  authagent만 뒤처진 게 아니라 애초에 NixOS 배포는 이 자동화 정책 전환 대상에
  포함된 적이 없다.

  **"기능이 있는데 왜 못 쓰나"에 대한 답 — 실제로는 쓸 수 있다, 선언 한 줄만
  빠졌을 뿐이다**: `deploy/nix/package.nix`(.deb 재포장 파생물)만 설치하고 이
  `nixosModules.default`를 시스템 설정에 import하지 않았다면, daemon/authagent
  systemd 서비스 자체가 애초에 생성되지 않는다 — 이 경우 TPM 없는 기기는 매번
  커널 유저 키링(재부팅/세션 종료 시 소실) 폴백으로 떨어져 "재부팅 후 재등록
  요구" 버그처럼 보이는 증상이 발생한다(§ linux_bio.rs 주석과 동일 현상).
  활성화하려면 NixOS 시스템 설정(flake 기준)에 다음을 추가한다:

    imports = [ tailpass.nixosModules.default ];
    services.tailpass-daemon.enable = true;
    services.tailpass-daemon.users = [ "<로그인 사용자명>" ];
    services.tailpass-authagent.enable = true;

  (`tailpass`는 이 저장소의 flake.nix를 가리키는 flake input 이름 — 사용자의
  flake.nix에서 원하는 이름으로 붙이면 된다.)
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
