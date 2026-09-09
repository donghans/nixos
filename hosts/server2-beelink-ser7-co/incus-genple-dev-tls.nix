# dev.genple.ai도 demo.genple.ai와 동일한 이유로 DNS-01 수동 챌린지가 필수다 —
# 자세한 배경은 incus-genple-demo-tls.nix 상단 주석 참고. 이 파일은 그 파일을
# genple-dev LXC / dev.genple.ai 대상으로 그대로 미러링한 것이다.
{
  pkgs,
  lib,
  ...
}: {
  systemd.services.incus-setup-genple-dev-tls = {
    description = "Install Caddy + acme.sh in genple-dev LXC for dev.genple.ai TLS (DNS-01 manual)";
    after = ["incus-setup-genple-dev.service"];
    requires = ["incus-setup-genple-dev.service"];
    partOf = ["incus-setup-genple-dev.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "120";
    };
    script = ''
      if incus exec genple-dev -- which caddy &>/dev/null; then
        exit 0
      fi

      incus exec genple-dev -- apk add --no-cache caddy curl openssl

      # acme.sh는 apk 패키지가 없어 공식 설치 스크립트 사용 (cron 자동 등록은 되지만
      # dns_manual 모드라 실제 갱신 시엔 사람이 TXT를 다시 넣어야 동작함)
      incus exec genple-dev -- sh -c '[ -x /root/.acme.sh/acme.sh ] || curl -s https://get.acme.sh | sh -s email=donghans@bitstep.it'

      # 인증서는 /root(700, root 전용) 아래가 아니라 /etc/caddy/certs 아래 caddy
      # 소유로 직접 설치한다 — caddy 서비스는 openrc에서 command_user=caddy:caddy로
      # 뜨기 때문에, /root 아래 두면 caddy 프로세스가 자기 인증서를 읽지 못해
      # "permission denied"로 죽는다(실제로 genple-dev에서 이 문제로 재현·확인함).
      incus exec genple-dev -- mkdir -p /etc/caddy/certs/dev.genple.ai
      incus exec genple-dev -- chown -R caddy:caddy /etc/caddy/certs

      incus exec genple-dev -- sh -c 'cat > /etc/caddy/Caddyfile' <<'CADDYFILE'
      {
          auto_https disable_redirects
      }
      dev.genple.ai {
          tls /etc/caddy/certs/dev.genple.ai/fullchain.cer /etc/caddy/certs/dev.genple.ai/dev.genple.ai.key
          reverse_proxy 127.0.0.1:80
      }
      CADDYFILE

      # 인증서가 아직 없으면 caddy가 시작에 실패하므로, 서비스 등록만 해두고
      # 기동은 인증서 발급 후 사람이 수동으로 한다 (아래 rc-service caddy start).
      incus exec genple-dev -- rc-update add caddy default

      echo "genple-dev: caddy + acme.sh 설치 완료." >&2
      echo "인증서 발급은 아직 안 됨 — 아래 절차를 genple-dev 컨테이너 안에서 직접 실행:" >&2
      echo "" >&2
      echo "1) incus exec genple-dev -- /root/.acme.sh/acme.sh --issue --dns dns_manual -d dev.genple.ai --yes-I-know-dns-manual-mode-enough-go-ahead-please" >&2
      echo "   → 출력된 TXT 레코드(_acme-challenge.dev.genple.ai)를 Squarespace DNS에 추가" >&2
      echo "2) TXT 전파 확인 후 (dig TXT _acme-challenge.dev.genple.ai) 같은 명령 다시 실행" >&2
      echo "3) incus exec genple-dev -- /root/.acme.sh/acme.sh --install-cert -d dev.genple.ai \\" >&2
      echo "     --cert-file /etc/caddy/certs/dev.genple.ai/cert.cer \\" >&2
      echo "     --key-file /etc/caddy/certs/dev.genple.ai/dev.genple.ai.key \\" >&2
      echo "     --fullchain-file /etc/caddy/certs/dev.genple.ai/fullchain.cer \\" >&2
      echo "     --reloadcmd 'chown -R caddy:caddy /etc/caddy/certs && rc-service caddy restart'" >&2
      echo "4) incus exec genple-dev -- rc-service caddy start" >&2
      echo "" >&2
      echo "90일 인증서 → 만료 전(약 60일차) 같은 1~3 절차 반복 필요 (Squarespace TXT 자동화 불가)" >&2
    '';
  };
}
