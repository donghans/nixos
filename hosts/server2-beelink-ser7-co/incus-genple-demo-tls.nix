# demo.genple.ai는 공인 IP가 아니라 Tailscale CGNAT IP(100.64.x.x)를 A 레코드로
# 직접 가리킨다(외부 노출 없이 Tailscale 사용자만 접근시키려는 의도) → Let's Encrypt가
# 80/443으로 직접 접근할 수 없어 HTTP-01/TLS-ALPN-01 챌린지가 원천적으로 불가능하다.
# 그래서 DNS-01 챌린지가 필수다.
#
# genple.ai 의 네임서버는 2026-11-05 Squarespace(googledomains) → AWS Route53 으로
# 위임했다(도메인 등록·결제는 Squarespace 에 그대로, 바뀐 것은 NS 뿐). Route53 호스티드
# 존은 Z10223562GL0655J868CH, 인증서 갱신용 IAM 사용자는 acme-genple-ai 이며
# 그 존의 TXT 만 고칠 수 있는 최소 권한이다(route53:ChangeResourceRecordSets,
# ListResourceRecordSets, GetChange, ListHostedZones*). 그래서 acme.sh 의 dns_aws 로
# 발급/갱신이 완전 자동이다(예전 dns_manual 은 90일마다 사람이 TXT 를 넣어야 해서
# 2026-10-20 에 만료 사고가 났다).
#
# 이 파일은 genple-demo LXC(Alpine) 안에 caddy + acme.sh를 설치하고 Caddyfile을
# 준비하며, IAM 키를 컨테이너로 밀어 넣는다. 키는 호스트의
# /var/lib/nix-secrets/route53/acme.env (root 600, AWS_ACCESS_KEY_ID=…/AWS_SECRET_ACCESS_KEY=…)
# 에 사람이 둔다(저장소에 없음). 최초 발급과 키 교체 때는 아래 "발급 절차"를 한 번 실행한다 —
# acme.sh 가 환경변수로 받은 키를 account.conf 에 스스로 저장해 이후 cron 갱신은 자동이다.
{
  pkgs,
  lib,
  ...
}: {
  systemd.services.incus-setup-genple-demo-tls = {
    description = "Install Caddy + acme.sh in genple-demo LXC for demo.genple.ai TLS (DNS-01 via Route53)";
    after = ["incus-setup-genple-demo.service"];
    requires = ["incus-setup-genple-demo.service"];
    partOf = ["incus-setup-genple-demo.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "120";
    };
    script = ''
      # IAM 키 주입은 caddy 가 이미 설치돼 있어도(아래 early-exit) 매번 수행한다 — 키 교체 반영용.
      if [ -f /var/lib/nix-secrets/route53/acme.env ]; then
        incus file push --mode 0600 /var/lib/nix-secrets/route53/acme.env genple-demo/root/.acme-route53.env \
          || echo "genple-demo: Route53 키 주입 실패(컨테이너 미기동?)" >&2
      else
        echo "genple-demo: /var/lib/nix-secrets/route53/acme.env 없음 — Route53 키 미주입" >&2
      fi

      if incus exec genple-demo -- which caddy &>/dev/null; then
        exit 0
      fi

      incus exec genple-demo -- apk add --no-cache caddy curl openssl

      # acme.sh는 apk 패키지가 없어 공식 설치 스크립트 사용 (cron 이 자동 갱신하며
      # dns_aws 로 Route53 에 TXT 를 직접 넣고 지운다)
      incus exec genple-demo -- sh -c '[ -x /root/.acme.sh/acme.sh ] || curl -s https://get.acme.sh | sh -s email=donghans@bitstep.it'

      # 인증서는 /root(700, root 전용) 아래가 아니라 /etc/caddy/certs 아래 caddy
      # 소유로 직접 설치한다 — caddy 서비스는 openrc에서 command_user=caddy:caddy로
      # 뜨기 때문에, /root 아래 두면 caddy 프로세스가 자기 인증서를 읽지 못해
      # "permission denied"로 죽는다(2026-09-09, genple-dev 최초 설치 때 이 문제로
      # 재현·확인. genple-demo는 최초 설정 당시 이미 이 경로로 수동 정정돼 있었음).
      incus exec genple-demo -- mkdir -p /etc/caddy/certs/demo.genple.ai
      incus exec genple-demo -- chown -R caddy:caddy /etc/caddy/certs

      incus exec genple-demo -- sh -c 'cat > /etc/caddy/Caddyfile' <<'CADDYFILE'
      {
          auto_https disable_redirects
      }
      demo.genple.ai {
          tls /etc/caddy/certs/demo.genple.ai/fullchain.cer /etc/caddy/certs/demo.genple.ai/demo.genple.ai.key
          reverse_proxy 127.0.0.1:80
      }
      CADDYFILE

      # 인증서가 아직 없으면 caddy가 시작에 실패하므로, 서비스 등록만 해두고
      # 기동은 인증서 발급 후 사람이 수동으로 한다 (아래 rc-service caddy start).
      incus exec genple-demo -- rc-update add caddy default

      echo "genple-demo: caddy + acme.sh 설치 완료." >&2
      echo "인증서 발급 절차(최초 1회·키 교체 때) — genple-demo 컨테이너 안에서:" >&2
      echo "" >&2
      echo "1) incus exec genple-demo -- sh -c 'set -a; . /root/.acme-route53.env; set +a; \\" >&2
      echo "     /root/.acme.sh/acme.sh --issue --dns dns_aws -d demo.genple.ai --keylength ec-256 --server letsencrypt'" >&2
      echo "   (acme.sh 가 키를 account.conf 에 저장 → 이후 갱신은 cron 이 자동)" >&2
      echo "2) incus exec genple-demo -- /root/.acme.sh/acme.sh --install-cert --ecc -d demo.genple.ai \\" >&2
      echo "     --cert-file /etc/caddy/certs/demo.genple.ai/cert.cer \\" >&2
      echo "     --key-file /etc/caddy/certs/demo.genple.ai/demo.genple.ai.key \\" >&2
      echo "     --fullchain-file /etc/caddy/certs/demo.genple.ai/fullchain.cer \\" >&2
      echo "     --reloadcmd 'chown -R caddy:caddy /etc/caddy/certs && rc-service caddy restart'" >&2
      echo "3) incus exec genple-demo -- rc-service caddy start" >&2
      echo "" >&2
      echo "90일 인증서 → acme.sh cron 이 만료 전에 자동 갱신(Route53 TXT 자동)." >&2
    '';
  };
}
