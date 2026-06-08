# TODO

> 이 파일은 2026-06-08 대화에서 도출된 아키텍처 결정 및 작업 목록이다.

---

## 1. Headscale → Vultr 단일 인스턴스 이전

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
| OS | NixOS (AMI or nixos-anywhere로 설치) |
| 트래픽 | 2TB/월 포함 |

### 실행 서비스

- headscale (control plane)
- DERP relay (현재 kr-ec2 relay 대체)
- nginx (프록시, e.772610158.xyz 인증서 종단)

### 작업

- [ ] Vultr 인스턴스 생성 (vultr-cli 스크립트 작성, `core/scripts/` or 루트)
- [ ] hosts/vultr-nixos-headscale.nix 생성
  - headscale 설정 (headscale.nix에서 분리 또는 재활용)
  - ip-forwarder 설정 (`hosts/_lib/ip-forwarder.nix` 활용)
  - DERP relay 설정
- [ ] rnixstrap으로 초기 배포
- [ ] Cloudflare e.772610158.xyz A레코드 → Vultr IP로 변경
- [ ] EC2 + Lightsail 인스턴스 종료

---

## 2. GitHub를 통한 headscale DB 보관

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

DB 내용이 대부분 공개키 + 메타데이터라 암호화 없이 private repo로도 충분.  
preauthkey/API key를 제거하면 사실상 전부 공개해도 무방한 데이터.

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

## 3. tailscale state 파일 → nixsec 관리

### 배경

tailscale `tailscaled.state` 파일 = machine key (비대칭 Curve25519)  
이것이 headscale에서 노드를 식별하는 실제 신원 (node key는 주기적 rotate됨)  
state 파일을 agenix로 관리하면 재배포 시 동일 노드로 재연결 가능 (preauthkey 불필요)

### headscale DB와의 대칭성

- headscale DB (노드 레코드) → GitHub
- tailscale state 파일 (노드 신원) → nixsec repo (agenix)
- 양쪽 모두 같은 git 기반에서 관리 → S3 날아가도 완전 재건 가능

### 작업

- [ ] 각 노드의 `/var/lib/tailscale/tailscaled.state` 수집
  - server2-beelink-ser7-co (100.64.0.2)
  - proxmox-ct101 / headscale-uxtxvylp (100.64.0.7)
  - vultr-nixos-headscale (이전 후)
- [ ] nixsec repo에 agenix 시크릿으로 추가:
  ```
  tailscale/state-server2-beelink-ser7-co.age
  tailscale/state-proxmox-ct101.age
  tailscale/state-vultr-headscale.age
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

---

## 4. preauthkey 폐기 → headscale node register 방식 전환

### 배경

현재: preauthkey (대칭 키) → 0.0.0.0/0 에서 접근 가능 → 보안 취약점  
목표: `headscale nodes register --key <nodekey>` 방식으로 전환

**흐름:**
```
1. nixup으로 배포 (tailscale 서비스 시작)
2. tailscaled가 WireGuard 키 쌍 자동 생성 → headscale에 등록 요청 → 대기
3. 관리자: headscale nodes list 확인 → headscale nodes register --user system --key <nodekey>
4. 노드 연결 완료
5. tailscaled.state → nixsec 백업 (이후 재배포 시 3~4 불필요)
```

**보안 특성:**
- WireGuard 공개키 기반 인증 (비대칭)
- 관리자 명시적 승인 필요 → 무단 노드 등록 불가
- 승인 후 state 파일이 신원 → 영구적

### 작업

- [ ] tailscale.nix 모듈에서 preauthkey 관련 로직 제거 (`preauthUser`, `preauthName` 옵션)
  - `tailscale-autoauth` 서비스에서 `--authkey` 플래그 제거
  - "BackendState가 Running이 아니면 `tailscale up` 후 대기" 구조로 단순화
- [ ] nixstrap.lib-preauth.sh, check_preauth_keys_* 함수 사용 호스트 정리
- [ ] rnixstrap 흐름에서 `check_preauth_keys_remote` 호출 제거 또는 조건부로

---

## 5. 부트스트랩 키 관리 (GitHub Apps + age)

### 결정 사항

| 키 | 역할 | 비고 |
|---|---|---|
| **age 개인키** | nixsec 복호화 | 영구, 로테이션 거의 없음 |
| **GitHub Apps SSH 키** | repo 클론/push 인증 | 독립적으로 로테이션 가능 |

두 키를 분리 유지. 합칠 경우 GitHub Apps 키 교체 시 nixsec 전체 재암호화가 필요해짐.

**부트스트랩 흐름 (rnixstrap):**
```
1. rnixstrap 실행 (age 키 + GitHub Apps 키 입력)
2. nixsec repo clone (GitHub Apps 키로 인증)
3. age 키로 nixsec 복호화 → secrets 획득
4. nixos-anywhere or nixos-rebuild switch
5. inject_secrets로 tailscale state 등 주입
6. 노드 연결 (preauthkey 없이 node register 방식)
```

### nixsec repo 공개 여부

age 암호화된 내용만 있으므로 public repo로 전환 가능.  
→ clone 시 GitHub 인증 불필요 → 부트스트랩 외부 의존성이 age 키 하나로 줄어듦.  
(단, public으로 바꾸면 암호화된 blob이 공개됨 — 허용 가능한 수준)

### 작업

- [ ] GitHub Apps 생성:
  - Installation A: nixsec repo → contents read-only
  - Installation B: headscale-backup repo → contents write
  - Installation C: nixos repo → contents read-only
- [ ] rnixstrap에 GitHub Apps JWT 토큰 발급 로직 추가 (현재는 gh CLI 의존)
- [ ] nixsec public 전환 여부 결정 후 진행

---

## 6. 공인 IP 포워딩 (DMZ) — mac studio / ubuntu-2404

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
- [ ] vultr-nixos-headscale.nix에 ip-forwarder 설정 추가
- [ ] source IP 보존 확인 (ubuntu-2404는 Linux이므로 policy routing 설정 가능)
- [ ] mac studio는 macOS policy routing 제약 — incus LXC 경유 방식 검토

---

## 7. CloudFormation / 인프라 코드 (보류)

Vultr 단일 인스턴스로 가면 CloudFormation 불필요. 대신:

- [ ] `vultr-setup.sh` 스크립트 (vultr-cli 기반, 레포 루트에 배치):
  ```bash
  vultr-cli instance list | grep -q "nixos-headscale" && exit 0
  vultr-cli instance create \
    --region icn --plan vc2-1c-2gb --os <nixos-os-id> \
    --host nixos-headscale
  ```

---

## 완료된 것 (이번 대화)

- [x] `hosts/deploy/` → `hosts/_deploy/` rename
- [x] `hosts/lib/` → `hosts/_lib/` rename  
- [x] `hosts/_lib/ip-forwarder.nix` 생성 (기존 eni-forwarding.nix를 import-with-args로 교체)
- [x] `mods/sys/services/_incus-tailscale-proxy-lib.nix` → `hosts/_lib/incus-tailscale-proxy.nix` 이동
- [x] 빈 `mods/sys/services/incus-tailscale-proxy.nix` 삭제
- [x] proxmox-ct101 (192.168.1.2) → 새 headscale 등록 + 192.168.1.0/24 route 승인
