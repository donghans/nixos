# step-ca 사설 PKI — AWS Roles Anywhere Trust Anchor용 CA
#
# [개요]
# 공개 CA(Let's Encrypt)는 AWS Roles Anywhere Trust Anchor로 등록할 수 없다.
# 이 모듈은 사설 루트 CA를 서비스로 띄우고 ACME 프로비저너를 활성화한다.
# 발급된 인증서를 aws-roles-anywhere 모듈이 소비해 임시 자격증명을 획득한다.
#
# [선행 작업 — 1회]
# 1. 로컬에서 CA 초기화:
#      step ca init \
#        --name "MyInfra CA" \
#        --dns localhost \
#        --address :8443 \
#        --provisioner admin
#    → root_ca.crt, intermediate_ca.crt, intermediate_ca.key, password 생성
# 2. root_ca.crt 내용 → AWS 콘솔: IAM Roles Anywhere → Trust Anchors → Create
#    (사설 CA이므로 공개 CA 오류 없이 등록 가능)
# 3. root_ca.crt 내용    → 이 모듈 rootCertPem 옵션
#    intermediate_ca.crt → 이 모듈 intermediateCertPem 옵션
# 4. intermediate_ca.key + password → passbolt 또는 vaultwarden에 보관
#
# [서버에 배치할 시크릿 — 배포 전 1회]
# sudo mkdir -p /var/lib/step-ca-secrets
# sudo install -m 644 intermediate_ca.key /var/lib/step-ca-secrets/intermediate_ca.key
# sudo install -m 600 password            /var/lib/step-ca-secrets/password
# * keyFile(644): DynamicUser 프로세스가 직접 읽음. 패스워드로 암호화된 키라 노출 허용범위.
# * passwordFile(600): systemd LoadCredential이 root 권한으로 읽어 서비스에 전달.
#
# [호스트별 설정 — hosts/<hostname>.nix]
# mods.sys.services.step-ca = {
#   dnsNames            = ["ca.ts.example.com"];  # Tailscale 호스트명
#   rootCertPem         = ''
#     -----BEGIN CERTIFICATE-----
#     ...
#     -----END CERTIFICATE-----
#   '';
#   intermediateCertPem = ''
#     -----BEGIN CERTIFICATE-----
#     ...
#     -----END CERTIFICATE-----
#   '';
# };
# * enable = true 는 <hostname>.toml [mods.sys.services] 에서 설정
# * PEM 내용은 문자열이라 toConfig를 거치지 못하므로 반드시 nix 파일에 직접 선언
#
# [인스턴스 교체 시]
# 새 서버에 시크릿 2개만 재주입하면 됨. CA 자체(루트/인터미디에이트 키)는 그대로 유지.
# AWS Trust Anchor 재등록 불필요.
#
# [배포 후 검증]
# systemctl status step-ca
# step ca health \
#   --ca-url https://<dnsName>:8443 \
#   --root /etc/step-ca/root_ca.crt
#
{
  mkMod,
  lib,
  ...
}:
mkMod __curPos "step-ca Private Certificate Authority" ({cfg, ...}: {
  options = {
    port = lib.mkOption {
      type = lib.types.port;
      default = 8443;
    };
    dnsNames = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      description = "CA 호스트명 목록 (Tailscale 호스트명, IP 등)";
    };
    rootCertPem = lib.mkOption {
      type = lib.types.str;
      description = "루트 CA 인증서 PEM 내용 (공개값, nix에 직접 포함)";
    };
    intermediateCertPem = lib.mkOption {
      type = lib.types.str;
      description = "인터미디에이트 CA 인증서 PEM 내용 (공개값, nix에 직접 포함)";
    };
    keyFile = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/step-ca-secrets/intermediate_ca.key";
      description = "인터미디에이트 CA 개인키 경로 (배포 전 수동 주입, 644)";
    };
    passwordFile = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/step-ca-secrets/password";
      description = "키 복호화 패스워드 파일 경로 (배포 전 수동 주입, 600)";
    };
  };
  os = {
    environment.etc."step-ca/root_ca.crt".text = cfg.rootCertPem;
    environment.etc."step-ca/intermediate_ca.crt".text = cfg.intermediateCertPem;

    services.step-ca = {
      enable = true;
      address = "0.0.0.0";
      port = cfg.port;
      intermediatePasswordFile = cfg.passwordFile;
      settings = {
        root = "/etc/step-ca/root_ca.crt";
        crt = "/etc/step-ca/intermediate_ca.crt";
        key = cfg.keyFile;
        dnsNames = cfg.dnsNames;
        db = {
          type = "badger";
          dataSource = "/var/lib/step-ca/db";
        };
        authority.provisioners = [
          {
            type = "ACME";
            name = "acme";
          }
        ];
        tls = {
          minVersion = 1.2;
          maxVersion = 1.3;
          renegotiation = false;
        };
      };
    };

    # DynamicUser + ProtectSystem=strict 환경에서 외부 시크릿 디렉터리 읽기 허용
    systemd.services.step-ca.serviceConfig.ReadOnlyPaths = [
      (builtins.dirOf cfg.keyFile)
    ];
  };
})
