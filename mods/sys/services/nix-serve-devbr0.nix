# 격리 개발 VM(devbr0)에 호스트 자신의 Nix 스토어를 캐시로 내어 준다 (plan dev-sandbox-pilot §11-2, Nix 빌드 캐시)
#
# 목적: `cache.nixos.org`(공개 캐시)에는 없는, 호스트가 이미 로컬에서 빌드해 둔 패키지(예: bitwarden-desktop,
# 소스 빌드에 약 26분)를 VM 이 재빌드하지 않고 그대로 받아 가게 한다. `nix-cache-proxy.nix`(공개 캐시의 풀스루 프록시)와는
# 다른 문제를 푼다 — 그건 업스트림에 있는 패키지만 줄이고, 이 문제(로컬 전용 빌드물)는 못 줄인다.
#
# 신뢰 경계: devbr0 전용(incusbr0·외부에는 안 엶) — `incus-devbr0.nix` 의 별도 nft 표에 예외를 더한다(같은 패턴: DNS 때처럼
# 브리지 주소 목적지로 제한). 서명 키는 로컬 생성·store 밖(`/var/lib/nix-serve-devbr0`)에 두어 git·nix 스토어에 들어가지 않는다
# (전역 지침: nix 에는 절대 시크릿을 넣지 않는다 — 이 키는 개인정보는 아니나 같은 보관 방식을 따른다).
#
# 되돌리는 법: 호스트 toml 의 `nix-serve-devbr0` 를 false 로 하고 nixup(서비스 중지, 방화벽 예외 제거). 키 파일은 안 지움(재사용 가능).
{mkMod, ...}:
mkMod __curPos "devbr0 전용 Nix 바이너리 캐시(호스트 스토어를 VM 에 내어 줌)" ({
  config,
  lib,
  pkgs,
  ...
}: {
  os = {
    assertions = [
      {
        assertion = config.mods.sys.services.incus-devbr0.enable;
        message = "mods.sys.services.nix-serve-devbr0 는 mods.sys.services.incus-devbr0.enable = true 가 필요합니다";
      }
    ];

    # 서명 키: 스토어 밖에 두고(활성화 때 없으면 생성), nix-serve 가 런타임에만 읽는다.
    system.activationScripts.nixServeDevbr0Key = ''
      mkdir -p /var/lib/nix-serve-devbr0
      if [ ! -s /var/lib/nix-serve-devbr0/cache-priv-key.pem ]; then
        ${pkgs.nix}/bin/nix-store --generate-binary-cache-key devbr0-nix-serve \
          /var/lib/nix-serve-devbr0/cache-priv-key.pem /var/lib/nix-serve-devbr0/cache-pub-key.pem
        chmod 600 /var/lib/nix-serve-devbr0/cache-priv-key.pem
      fi
    '';

    services.nix-serve = {
      enable = true;
      bindAddress = "10.100.1.1"; # devbr0 브리지 주소에만 — 다른 인터페이스에는 안 들림
      port = 5000;
      secretKeyFile = "/var/lib/nix-serve-devbr0/cache-priv-key.pem";
      openFirewall = false; # 방화벽 예외는 incus-devbr0.nix 의 devbr0-guard 체인 안에 직접 둔다(이 모듈의 enable 을 그 모듈이 읽음) —
      # 별도 nft 표로 두면 devbr0-guard 의 마지막 drop 과 같은 hook+priority 라 평가 순서가 보장되지 않아 2026-11-22 접속 안 됨으로 재현됨.
    };
  };
})
