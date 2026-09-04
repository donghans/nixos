# demo.genple.ai는 공인 IP가 아니라 Tailscale CGNAT IP(100.64.x.x)를 A 레코드로
# 직접 가리킨다(외부 노출 없이 Tailscale 사용자만 접근시키려는 의도) → Let's Encrypt가
# 80/443으로 직접 접근할 수 없어 HTTP-01/TLS-ALPN-01 챌린지가 원천적으로 불가능하다.
# 그래서 DNS-01 챌린지가 필수인데, genple.ai의 DNS는 Squarespace가 관리하고
# Squarespace는 Caddy/lego용 DNS-01 API 플러그인이 없다 → acme.sh의 dns_manual 모드로
# 매 발급/갱신 시 TXT 레코드를 사람이 직접 Squarespace에 추가해야 한다(완전 자동화 불가).
#
# 이 파일은 genple-demo LXC(Alpine) 안에 caddy + acme.sh를 설치하고 Caddyfile을
# 준비하는 것까지만 한다. 실제 인증서 발급(DNS TXT 수동 등록)은 대화형 작업이라
# 이 systemd 서비스가 대신할 수 없다 — 최초 1회는 아래 "발급 절차" 안내를 따라
# 사람이 직접 실행해야 한다.
{
  pkgs,
  lib,
  ...
}: {
  systemd.services.incus-setup-genple-demo-tls = {
    description = "Install Caddy + acme.sh in genple-demo LXC for demo.genple.ai TLS (DNS-01 manual)";
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
      if incus exec genple-demo -- which caddy &>/dev/null; then
        exit 0
      fi

      incus exec genple-demo -- apk add --no-cache caddy curl openssl

      # acme.sh는 apk 패키지가 없어 공식 설치 스크립트 사용 (cron 자동 등록은 되지만
      # dns_manual 모드라 실제 갱신 시엔 사람이 TXT를 다시 넣어야 동작함)
      incus exec genple-demo -- sh -c '[ -x /root/.acme.sh/acme.sh ] || curl -s https://get.acme.sh | sh -s email=donghans@bitstep.it'

      incus exec genple-demo -- mkdir -p /root/certs/demo.genple.ai

      incus exec genple-demo -- sh -c 'cat > /etc/caddy/Caddyfile' <<'CADDYFILE'
      demo.genple.ai {
          tls /root/certs/demo.genple.ai/fullchain.cer /root/certs/demo.genple.ai/demo.genple.ai.key
          reverse_proxy 127.0.0.1:80
      }
      CADDYFILE

      # 인증서가 아직 없으면 caddy가 시작에 실패하므로, 서비스 등록만 해두고
      # 기동은 인증서 발급 후 사람이 수동으로 한다 (아래 rc-service caddy start).
      incus exec genple-demo -- rc-update add caddy default

      echo "genple-demo: caddy + acme.sh 설치 완료." >&2
      echo "인증서 발급은 아직 안 됨 — 아래 절차를 genple-demo 컨테이너 안에서 직접 실행:" >&2
      echo "" >&2
      echo "1) incus exec genple-demo -- /root/.acme.sh/acme.sh --issue --dns dns_manual -d demo.genple.ai --yes-I-know-dns-manual-mode-enough-go-ahead-please" >&2
      echo "   → 출력된 TXT 레코드(_acme-challenge.demo.genple.ai)를 Squarespace DNS에 추가" >&2
      echo "2) TXT 전파 확인 후 (dig TXT _acme-challenge.demo.genple.ai) 같은 명령 다시 실행" >&2
      echo "3) incus exec genple-demo -- /root/.acme.sh/acme.sh --install-cert -d demo.genple.ai \\" >&2
      echo "     --cert-file /root/certs/demo.genple.ai/cert.cer \\" >&2
      echo "     --key-file /root/certs/demo.genple.ai/demo.genple.ai.key \\" >&2
      echo "     --fullchain-file /root/certs/demo.genple.ai/fullchain.cer \\" >&2
      echo "     --reloadcmd 'rc-service caddy restart'" >&2
      echo "4) incus exec genple-demo -- rc-service caddy start" >&2
      echo "" >&2
      echo "90일 인증서 → 만료 전(약 60일차) 같은 1~3 절차 반복 필요 (Squarespace TXT 자동화 불가)" >&2
    '';
  };
}
