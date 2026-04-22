# 모니터링 리팩터: Cockpit → Netdata

## 목표

- Netdata로 모니터링 대체 — 호스트, Incus VM, 컨테이너 메트릭을 단일 대시보드로 집계
- 서비스 관리는 기존대로 `nixup switch` + `systemctl` 터미널로 유지

---

## 완료된 작업

- `mods/sys/services/cockpit.nix` 삭제
- `mods/sys/services/frp.nix` 삭제
- `mods/sys/services/headscale.nix` 삭제
- 모든 preset TOML (`_preset.iso`, `_preset.workstation`, `_preset.server`) 에서 `cockpit`, `frp`, `headscale` 항목 제거
- `hosts/lightsail-headscale.toml` 에서 `headscale = true`, `cockpit = false` 제거
- `hosts/lightsail-headscale.nix` 에 `services.headscale.enable = true` 직접 추가
- `rnixstrap.lib-input.sh` ask_services에서 headscale, cockpit 항목 제거
- `rnixstrap.task-setup.sh` all_services 및 nix stub 생성 로직에서 headscale, cockpit 제거

---

## 아키텍처 (Netdata)

```
물리 서버 (Netdata Parent)
├── netdata (parent mode) — 집계 + 웹 UI (포트 19999)
└── Incus VM 1..N
    └── netdata (child mode) — 메트릭 → parent로 스트리밍

원격 서버 (deploy-rs 배포 대상)
└── netdata (standalone or child) — 필요 시 parent로 스트리밍
```

- 물리 서버의 Netdata Parent가 모든 child 메트릭을 수집 → 단일 URL로 전체 현황 확인
- 원격 서버는 독립 standalone으로 운영하거나, 물리 서버 Parent에 연결 가능

---

## 남은 작업

### 1. Netdata 모듈 추가

**공통 모듈** (`mods/sys/services/netdata.nix` 신규):

```nix
{ config, lib, ... }:
{
  services.netdata = {
    enable = true;
    config = {
      global = {
        "update every" = 2;
      };
    };
  };

  networking.firewall.allowedTCPPorts = [ 19999 ];
}
```

**Parent 설정** (물리 서버 host config에 추가):

```nix
services.netdata.config.stream = {
  "enabled" = "yes";
  "api key" = "<UUID>";  # uuidgen으로 생성
};
```

**Child 설정** (Incus VM / 원격 서버):

```nix
services.netdata.configDir."stream.conf" = pkgs.writeText "stream.conf" ''
  [stream]
  enabled = yes
  destination = <parent-ip>:19999
  api key = <동일 UUID>
'';
```

### 2. Incus exporter (선택)

Incus VM 내부에 Netdata 설치하면 자동으로 컨테이너 메트릭 수집됨.
물리 호스트의 Netdata는 `incus` 플러그인으로 호스트 레벨 Incus 현황도 수집 가능 — nixpkgs Netdata 패키지에 포함 여부 확인 필요.

---

## 검토 필요 사항

- [ ] 물리 서버 host config 위치 결정 (아직 생성 전)
- [ ] Netdata Parent ↔ Child 스트리밍용 API key 생성 및 secrets 관리 방식 결정
  - `sops-nix` 또는 `.env` 파일로 관리 고려
- [ ] 원격 서버(lightsail 등)를 Parent에 연결할지 standalone으로 둘지 결정
- [ ] Netdata 웹 UI 외부 노출 범위 (로컬 only vs Tailscale/Headscale 경유)

---

## 완료 기준

- `nixup switch` 후 `http://<물리서버>:19999` 에서 호스트 + Incus VM 메트릭 모두 확인 가능
