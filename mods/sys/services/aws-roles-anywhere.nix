# AWS IAM Roles Anywhere — 적용 절차
#
# [개요]
# Let's Encrypt 인증서(DNS-01/Cloudflare)를 Trust Anchor로 등록해
# 임시 자격증명을 온디맨드 발급받는 방식. 정적 액세스 키 불필요.
# Lightsail처럼 IAM Instance Profile 연결 불가한 환경을 위한 해법.
#
# [AWS 콘솔 선행 작업 — 계정당 1회]
# 1. IAM Roles Anywhere → Trust Anchors → Create
#    External certificate bundle: ISRG Root X1 PEM 붙여넣기
#    (https://letsencrypt.org/certs/isrgrootx1.pem)
# 2. IAM → Roles → Create Role
#    Trusted entity: IAM Roles Anywhere → 위에서 만든 Trust Anchor + Profile 선택
#    필요 권한만 부여 (AmazonSSMManagedInstanceCore + 필요한 서비스 정책)
# 3. IAM Roles Anywhere → Profiles → Create
#    위에서 만든 Role 연결
#
# [호스트별 설정 — hosts/<hostname>.nix]
# mods.sys.services.aws-roles-anywhere = {
#   domain         = "r.772610158.xyz";     # 인증서 도메인 (Cloudflare 관리)
#   trustAnchorArn = "arn:aws:rolesanywhere:...";
#   profileArn     = "arn:aws:rolesanywhere:...";
#   roleArn        = "arn:aws:iam::...";
# };
# * enable = true 는 <hostname>.toml [mods.sys.services] 에서 설정
# * ARN은 문자열이라 toConfig를 거치지 못하므로 반드시 nix 파일에 직접 선언
#
# [서버에 배치할 시크릿 — 배포 전 1회]
# sudo mkdir -p /var/lib/secrets
# echo 'CF_DNS_API_TOKEN=<토큰>' | sudo tee /var/lib/secrets/cloudflare-token
# sudo chmod 600 /var/lib/secrets/cloudflare-token
# * Cloudflare 토큰 권한: Zone / DNS / Edit (해당 도메인만)
#
# [인스턴스 교체 시]
# Cloudflare 토큰만 새 서버에 배치하면 됨.
# security.acme가 새 인증서 자동 발급 → Trust Anchor(ISRG Root X1)가 그대로 신뢰.
# AWS 콘솔 재작업 불필요.
#
# [SSM Session Manager — Lightsail 브라우저 콘솔 대체]
# IAM Role에 AmazonSSMManagedInstanceCore 정책 부여 시 SSM Session Manager 사용 가능.
# SSM Agent는 기본적으로 Lightsail IMDS(계정 102212213358) 자격증명을 집어가는데,
# 이 모듈이 amazon-ssm-agent 서비스에 AWS_CONFIG_FILE을 주입해 credential_process를
# 우선 사용하도록 강제함 → 계정 732799293614으로 SSM 등록됨.
# 활성화 후: aws ssm start-session --target <instance-id>
#
# [배포 후 검증]
# systemctl status acme-r.772610158.xyz.service  # 인증서 발급 확인
# aws sts get-caller-identity                     # 계정 732799293614 반환되면 성공
# systemctl status amazon-ssm-agent              # SSM 등록 확인 (AmazonSSMManagedInstanceCore 부여 시)
#
{
  mkMod,
  pkgs,
  config,
  lib,
  ...
}:
mkMod __curPos "AWS IAM Roles Anywhere — cert-based temporary credentials" ({cfg, ...}: {
  options = {
    domain = lib.mkOption {
      type = lib.types.str;
      description = "ACME cert domain (e.g. r.772610158.xyz)";
    };
    trustAnchorArn = lib.mkOption {type = lib.types.str;};
    profileArn = lib.mkOption {type = lib.types.str;};
    roleArn = lib.mkOption {type = lib.types.str;};
    dnsProvider = lib.mkOption {
      type = lib.types.str;
      default = "cloudflare";
    };
    tokenFile = lib.mkOption {
      type = lib.types.str;
      default = "/var/lib/secrets/cloudflare-token";
      description = "Path to env file with CF_DNS_API_TOKEN=... (one line)";
    };
    awsRegion = lib.mkOption {
      type = lib.types.str;
      default = "ap-northeast-2";
    };
    caServer = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "내부 ACME CA URL (step-ca). null이면 Let's Encrypt 사용.";
    };
    caCert = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "내부 CA 루트 인증서 PEM. caServer 사용 시 시스템 트러스트에 추가됨.";
    };
  };
  os = {
    security.acme.acceptTerms = true;
    security.acme.defaults.email = config.workspace.gitEmail;
    security.acme.certs.${cfg.domain} =
      {
        inherit (cfg) dnsProvider;
        environmentFile = cfg.tokenFile;
        group = "aws-access";
        keyType = "rsa2048";
        extraLegoRunFlags = ["--dns.resolvers=1.1.1.1:53"];
      }
      // lib.optionalAttrs (cfg.caServer != null) {
        server = cfg.caServer;
      };

    security.pki.certificates = lib.optional (cfg.caCert != null) cfg.caCert;

    users.groups.aws-access = {};
    users.users.${config.workspace.username}.extraGroups = ["aws-access"];

    environment.systemPackages = [pkgs.aws-signing-helper pkgs.awscli2];

    environment.etc."aws/config".text = ''
      [default]
      credential_process = ${pkgs.aws-signing-helper}/bin/aws_signing_helper credential-process \
        --certificate /var/lib/acme/${cfg.domain}/cert.pem \
        --private-key /var/lib/acme/${cfg.domain}/key.pem \
        --trust-anchor-arn ${cfg.trustAnchorArn} \
        --profile-arn ${cfg.profileArn} \
        --role-arn ${cfg.roleArn}
      region = ${cfg.awsRegion}
    '';

    environment.sessionVariables.AWS_CONFIG_FILE = "/etc/aws/config";

    # SSM Agent가 Lightsail IMDS(계정 102212213358) 대신 credential_process를 사용하도록 강제
    # (AWS SDK 자격증명 체인: config file credential_process > IMDS)
    systemd.services.amazon-ssm-agent.environment.AWS_CONFIG_FILE = "/etc/aws/config";
  };
})
