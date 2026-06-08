# TODO

> 이 파일은 2026-06-08 대화에서 도출된 아키텍처 결정 및 작업 목록이다.

---

## 1. GitHub를 통한 headscale DB 보관

### 배경

현재: headscale SQLite DB → S3 (litestream)  
문제: S3가 날아가면 폴백 없음, EC2와 S3 의존성이 묶여있음  
목표: headscale DB를 GitHub에도 보관해 S3 의존성 제거 + 대칭적 재건 가능

### 설계

```
headscale DB (SQLite)
  → sqlite3 db.sqlite .dump → headscale.sql (텍스트, git diff 가능)
  → systemd timer (hourly)
  → git commit + push (GitHub Apps 키로 인증)
  → private GitHub repo
```

DB 내용이 대부분 공개키 + 메타데이터. preauthkey/API key 제거 시 사실상 공개 무방한 데이터.  
→ **age 암호화 불필요**, private repo로 접근 제어만으로 충분.  
(nixsec와 달리 private key가 포함되지 않으므로 암호화 레이어 생략)

### 작업

- [ ] GitHub Apps 생성 (headscale-backup repo write 권한)
- [ ] headscale-backup GitHub repo 생성
- [ ] Vultr headscale NixOS 설정에 백업 systemd timer 추가:

  ```nix
  systemd.services.headscale-db-backup = {
    script = ''
      sqlite3 /var/lib/headscale/db.sqlite .dump \
        > /var/lib/nix-secrets/headscale/headscale.sql
      cd /path/to/nixos-repo
      git add headscale/headscale.sql
      git diff --cached --quiet || git commit -m "chore: headscale db backup"
      git push
    '';
    serviceConfig.Type = "oneshot";
  };
  systemd.timers.headscale-db-backup = {
    timerConfig.OnCalendar = "hourly";
    wantedBy = [ "timers.target" ];
  };
  ```

- [ ] 복구 절차 문서화: `sqlite3 db.sqlite < headscale.sql`

---

## 2. Headscale → Vultr 단일 인스턴스 이전

> **전제조건: TODO 1 (GitHub DB backup) 동작 확인 완료 후 진행**

### 배경

현재 구조: EC2 (headscale) + Lightsail (proxy) + S3 (DB 백업) — 세 서비스로 분산  
목표 구조: Vultr 단일 인스턴스 하나로 통합

**이전 이유:**
- S3 의존성이 사라지면 EC2를 쓸 이유가 없음
- Lightsail은 IP 1개 고정 → 추가 IP 대응 어려움
- Vultr: 대표님 선호, 2GB RAM $10/월 + 2TB 트래픽 포함, 관리 단순화
- 장애 시 Lightsail 하나 띄우고 Cloudflare DNS A레코드만 변경하면 복구 가능
  - nixos-anywhere로 fresh 서버에 NixOS 즉시 설치 가능 (disaster recovery 경로 명확)

### 인스턴스 스펙

| 항목 | 값 |
|---|---|
| 프로바이더 | Vultr |
| 플랜 | Regular Performance 2GB ($10/월) |
| 리전 | 서울 (icn) |
| OS | NixOS (nixos-anywhere로 설치) |
| 트래픽 | 2TB/월 포함 |

### 실행 서비스

- headscale (control plane)
- DERP relay (현재 kr-ec2 relay 대체)
- nginx (프록시, e.772610158.xyz 인증서 종단)

### e2 스테이징 플로우 (중단 최소화 전략)

`e.772610158.xyz`는 사내 서빙 중 → 직접 전환하지 않고 e2로 먼저 검증 후 DNS 교체.

```
1. Vultr 인스턴스 생성, headscale config server_url = e2.772610158.xyz
   (Cloudflare DNS: e2.772610158.xyz A → Vultr IP)
2. 관리자 본인만 e2에 tailscale 등록해 동작 검증
   (SSH 연결, 멀티 NIC, DERP relay 등 안정화 확인)
3. 검증 완료 → headscale DB를 EC2 → Vultr로 덤프/복원
   (sqlite3 /var/lib/headscale/db.sqlite .dump > headscale.sql → 신규 서버에서 sqlite3 db.sqlite < headscale.sql)
4. headscale config server_url = e.772610158.xyz 로 변경 후 nixup
5. Cloudflare DNS: e.772610158.xyz A → Vultr IP 변경
   기존 클라이언트들은 DNS 변경만으로 자동으로 Vultr headscale에 연결됨
6. EC2 + Lightsail 종료
```

### 작업

- [ ] Vultr 인스턴스 생성 (TODO 6 스펙 참조, 웹 콘솔에서 수동 생성)
- [ ] `hosts/headscale-vps.nix` 생성 (`ec2-nixos-headscale` 기반으로 재작성)
  - `headscaleDomain`을 NixOS option으로 분리 (e2↔e 한 줄 전환용)
  - DERP region name "Korea (EC2)" → "Korea (VPS)"로 교체
  - `users.users.ec2-user` 제거 (EC2 특화 설정)
  - litestream/S3 백업 → GitHub 백업 timer로 교체 (TODO 1)
  - ip-forwarder 설정 (`hosts/_lib/ip-forwarder.nix` 활용)
- [ ] `hosts/headscale-vps.toml` 생성
- [ ] e2 스테이징: Cloudflare e2.772610158.xyz DNS 추가 후 검증
- [ ] e2 검증 완료 후 DB 이전 + e.772610158.xyz DNS 교체
- [ ] EC2 + Lightsail 인스턴스 종료

---

## 3. tailscale state 파일 → nixsec 관리

### 배경

tailscale `tailscaled.state` 파일 = machine key (비대칭 Curve25519)  
이것이 headscale에서 노드를 식별하는 실제 신원 (node key는 주기적 rotate됨)  
state 파일을 agenix로 관리하면 재배포/하드웨어 교체 시 동일 노드로 재연결 가능

### headscale DB와의 대칭성

- headscale DB (노드 레코드) → GitHub (TODO 1)
- tailscale state 파일 (노드 신원) → nixsec repo (agenix, private)
- 양쪽 모두 git 기반 → NixOS + GitHub + 키 파일만으로 완전 재건 가능

### 지원 시나리오 및 위험도

| 시나리오 | 위험도 | 비고 |
|---|---|---|
| 동일 머신 NixOS 재배포 후 복원 | 낮음 | machine key 동일, headscale이 node key 재협상 |
| 물리 머신 교체 (구 머신 완전 사망) | 낮음~중간 | 동시 실행 없으므로 node 충돌 없음 |
| 구 머신 살아있는 상태에서 복원 | 높음 | 이 시나리오는 절차로 방지 (구 머신 먼저 종료) |

> **NixOS(Linux) 한정**: state 파일이 TPM 없이 순수 파일로 존재. macOS/Windows와 달리 하드웨어 종속 암호화 없음 → 복사/복원 가능.  
> headscale은 self-hosted라 admin이 직접 노드 관리 가능 → 불일치 시 수동 fix 가능.

### 복원 실패 시 대응 절차

state 복원 후 tailscale 연결이 안 될 경우:
```bash
headscale nodes list                          # 해당 노드 확인
headscale nodes delete --identifier <id>      # 노드 삭제
tailscale up                                  # 재등록 요청 대기
headscale nodes register --user system --key <nodekey>  # admin 승인
# 연결 확인 후 state 재백업
```

### 작업

- [ ] 각 노드의 `/var/lib/tailscale/tailscaled.state` 수집
  - server2-beelink-ser7-co (100.64.0.2)
  - proxmox-ct101 / headscale-uxtxvylp (100.64.0.7) — headscale에 이미 등록됨, 192.168.1.0/24 route 승인 완료
  - headscale-vps (이전 후)
- [ ] nixsec repo에 agenix 시크릿으로 추가:
  ```
  tailscale/state-server2-beelink-ser7-co.age
  tailscale/state-proxmox-ct101.age
  tailscale/state-headscale-vps.age
  ```
- [ ] 각 호스트의 `hosts/_deploy/<hostname>.secrets/secrets.json`에 주입 설정 추가:
  ```json
  {
    "groups": {
      "tailscale": {
        "repo": "org/nixsec",
        "secrets": {
          "tailscale/state-<hostname>": "var/lib/tailscale/tailscaled.state"
        }
      }
    }
  }
  ```
- [ ] inject_secrets → nixos-rebuild 순서에서 tailscaled 재시작 확인
  (inject 후 nixos-rebuild switch가 tailscaled를 재시작하면서 injected state를 읽음)
- [ ] nixsec박제 완료 후: `tailscale.nix`에서 preauthkey 관련 로직 제거
  - `preauthUser`, `preauthName` 옵션 제거
  - `tailscale-autoauth` 서비스에서 `--authkey` 플래그 제거
  - `nixstrap.lib-preauth.sh`, `check_preauth_keys_*` 함수 사용 호스트 정리

---

## 4. 부트스트랩 키 관리 (GitHub Apps + age)

### 결정 사항

| 키 | 역할 | 비고 |
|---|---|---|
| **age 개인키** | nixsec 복호화 | 영구, 로테이션 거의 없음 |
| **GitHub Apps 키 (RSA/JWT)** | repo 클론/push 인증 | 독립적으로 로테이션 가능, user 비종속 |

두 키를 분리 유지. 합칠 경우 GitHub Apps 키 교체 시 nixsec 전체 재암호화가 필요해짐.

**인증 방식: GitHub Apps (확정)**
- PAT: user 종속 + 낮은 엔트로피 → 기각
- Deploy key: repo-specific이지만 GitHub Apps가 다중 repo 통합 관리에 적합
- GitHub Apps (JWT+RSA): user 비종속, fine-grained permission, 독립 로테이션 → 채택

**부트스트랩 흐름 (rnixstrap):**
```
1. rnixstrap 실행 (age 키 + GitHub Apps 키 입력)
2. nixsec repo clone (GitHub Apps 키로 인증)
3. age 키로 nixsec 복호화 → secrets 획득
4. nixos-anywhere or nixos-rebuild switch
5. inject_secrets로 tailscale state 등 주입
6. 노드 연결 (TODO 3 nixsec박제 완료 후 preauthkey 불필요)
```

### nixsec repo 공개 여부

**private 유지 (결정 완료)**. tailscale state 파일(Curve25519 private key) 포함 → 암호화 + private 둘 다 필요.  
접근 자체를 막는 것이 암호화 강도에 의존하는 것보다 우수한 보안 전략.

### 작업

- [ ] GitHub Apps 생성:
  - Installation A: nixsec repo → contents read-only
  - Installation B: headscale-backup repo → contents write
  - Installation C: nixos repo → contents read-only (deploy-rs 빌드용)
- [ ] rnixstrap에 GitHub Apps JWT 토큰 발급 로직 추가 (현재는 gh CLI 의존)

---

## 5. 공인 IP 포워딩 (DMZ) — mac studio / ubuntu-2404

### 배경

mac studio와 ubuntu-2404 (incus VM)에 공인 IP를 부여해 어떤 포트로도 직접 접근 가능하도록.  
현재 EC2 ENI 방식 → Vultr secondary IP로 전환.

### 구조

```
인터넷 → Vultr (IP1=headscale, IP2=mac studio용, IP3=ubuntu-2404용)
                ↓ nftables DNAT (hosts/_lib/ip-forwarder.nix)
          tailscale 터널
                ↓
         mac studio (100.64.0.5) / ubuntu-2404 (100.64.0.12)
```

`hosts/_lib/ip-forwarder.nix` 이미 구현됨. Vultr 호스트에서:

```nix
imports = [
  (import ./_lib/ip-forwarder.nix { inherit lib; }) {
    interface    = "eth0";
    gateway      = "<vultr-gateway>";
    subnetPrefix = 24;
    forwards = [
      { publicIp = "<IP2>"; targetTs = "100.64.0.5";  }
      { publicIp = "<IP3>"; targetTs = "100.64.0.12"; }
    ];
  }
];
```

### 작업

- [ ] Vultr 인스턴스 생성 후 secondary IP 2개 신청
- [ ] headscale-vps.nix에 ip-forwarder 설정 추가
- [ ] source IP 보존 확인 (ubuntu-2404는 Linux이므로 policy routing 설정 가능)
- [ ] mac studio는 macOS policy routing 제약 — incus LXC 경유 방식 검토
  (`hosts/_lib/incus-tailscale-proxy.nix` 참조)

---

## 6. Vultr 인스턴스 스펙 (수동 생성)

일회성 작업이라 vultr-cli 스크립트 불필요 — Vultr 웹 콘솔에서 직접 생성.

| 항목 | 값 |
|---|---|
| 리전 | 서울 (icn) |
| 플랜 | Regular Cloud Compute, 1 vCPU / 2GB RAM (vc2-1c-2gb, $10/월) |
| OS | Debian 12 또는 Ubuntu 22.04 (nixos-anywhere로 덮어씀) |
| 호스트명 | headscale-vps |
| Secondary IP | 2개 추가 신청 (mac studio용, ubuntu-2404용) |
