# 원격 스탠드얼론 서버 부트스트랩 계획

## 개요

NixOS 레포 자체를 원격 서버에 1회성으로 전달해 완전히 자립적인(standalone)
관리 서버를 만드는 기능. 이후 해당 서버는 `nixup` / `rnixup`으로 자기 자신과
다른 원격 서버들을 관리하는 컨트롤 플레인이 된다.

---

## 컨트롤 플레인 서버 구성

한 대의 서버에 아래 세 역할을 집약한다.

| 역할 | 모듈 | 비고 |
|------|------|------|
| Tailscale 코디네이터 | `mods.sys.services.headscale` | 인터넷 노출 필수 |
| 사설 CA | `mods.sys.services.step-ca` | tailnet + 인터넷 양쪽 접근 가능 |
| Nix 바이너리 캐시 프록시 | `mods.sys.services.nix-cache-proxy` | tailnet 내부 전용 |

프리셋 후보: `_preset.control-plane.toml`

### headscale + step-ca 동거 이유

- headscale 서버는 어차피 인터넷에 노출되어 있으므로, CA도 별도 공개 IP 없이
  인터넷에서 도달 가능 → tailnet 합류 전 신규 서버도 CA에 직접 접근 가능.
- 이 서버가 살아있으면 나머지 모든 인프라가 동작하는 구조 → 의존성 체인이 단순하고 명확.
- 단일 장애점(SPOF) 문제는 키 백업 + 빠른 재부트스트랩으로 수용 가능한 리스크.
  (기존 인증서는 유효 기간 동안 계속 동작, headscale 재등록만 처리하면 됨)

---

## rnixstrap-remote 설계

### 목표

```bash
nixup remote-bootstrap <hostname>
```

한 번의 명령으로:
1. 원격 서버에 NixOS 레포를 전달
2. NixOS 설치 (`nixos-anywhere` 활용)
3. `deploy-rs`로 최종 설정 배포
4. 이후 해당 서버가 `nixup` / `rnixup`으로 자기 자신을 관리 가능

### 현재 rnixstrap과의 차이

| | 현재 rnixstrap | remote-bootstrap |
|---|---|---|
| 대상 | 물리/VM (콘솔 접근) | 원격 서버 (SSH만 있으면 됨) |
| 레포 전달 | 불필요 (로컬 실행) | 필요 (레포 전체 or flake tarball 전송) |
| nixup 사용 | 로컬에서만 | 서버 자체에서도 가능 |
| 주 용도 | 워크스테이션/랩탑 | 클라우드 서버 (Lightsail 등) |

### 구현 단계

**1단계: 레포 전달**
- `git archive` 또는 `rsync`로 레포를 원격 서버 `/opt/nixos`에 전송
- nix flake의 경우 `nix copy` 활용 가능

**2단계: NixOS 설치**
- `nixos-anywhere --flake .#<hostname>` (현재 rnixstrap과 동일)
- SSH 키는 `~/.ssh/rnixup/<hostname>.pem` 패턴 유지

**3단계: 시크릿 주입**
- 컨트롤 플레인 서버라면: step-ca 키 파일 주입
  ```bash
  scp intermediate_ca.key root@<server>:/var/lib/step-ca-secrets/
  scp password            root@<server>:/var/lib/step-ca-secrets/
  ```
- Cloudflare 토큰 등 기타 시크릿도 동일 패턴

**4단계: deploy-rs 배포**
- `deploy .#<hostname>` (현재와 동일)

**5단계: 자립 확인**
- `ssh root@<server> nixup check` 또는 `nixup self` 커맨드

### hosts/<hostname>.toml 추가 필드 검토

```toml
[deploy]
ip     = "..."
sshKey = "~/.ssh/rnixup/<hostname>.pem"
cloud  = "aws"

[bootstrap]
standalone = true          # nixup/rnixup 레포 전달 여부
repoPath   = "/opt/nixos"  # 서버 내 레포 경로 (기본값)
```

---

## 키 백업 전략

컨트롤 플레인 서버에서 외부 보관이 필요한 시크릿:

| 파일 | 저장 위치 | 권한 |
|------|----------|------|
| `intermediate_ca.key` | passbolt / vaultwarden | 644 (암호화된 키) |
| `password` (CA 키 패스워드) | passbolt / vaultwarden | 600 |
| headscale private key | passbolt / vaultwarden | 600 |
| `~/.ssh/rnixup/*.pem` | 로컬 + passbolt | 600 |

### 복구 시나리오

서버가 완전히 날아간 경우:
1. 새 서버 프로비저닝 (Lightsail 콘솔)
2. `nixup remote-bootstrap control-plane` (1회 명령)
3. passbolt에서 키 파일 복원 → `/var/lib/step-ca-secrets/` 주입
4. `systemctl restart step-ca headscale`
5. 기존 tailnet 노드들 자동 재연결 (headscale DB가 레포에 포함되어 있으면 즉시, 아니면 재등록)

목표 복구 시간: **30분 이내**

---

## 부트스트랩 의존성 체인

```
[1] remote-bootstrap → 컨트롤 플레인 서버 (headscale + step-ca + nix-cache)
         ↓
[2] 컨트롤 플레인 서버 기동 → headscale 활성화
         ↓
[3] 신규 서버 rnixstrap → tailnet 합류
         ↓
[4] step-ca ACME → 인증서 발급 (tailnet 경유)
         ↓
[5] aws-roles-anywhere → AWS 임시 자격증명 동작
         ↓
[6] SSM Session Manager → 브라우저 콘솔 없이 접속 가능
```

---

## 구현 우선순위

| 순서 | 작업 | 상태 |
|------|------|------|
| 1 | `mods/sys/services/step-ca.nix` 구현 | 계획 완료 → 구현 대기 |
| 2 | `aws-roles-anywhere.nix` caServer/caCert 옵션 추가 | 계획 완료 → 구현 대기 |
| 3 | `_preset.control-plane.toml` 정의 | 미착수 |
| 4 | `nixup remote-bootstrap` 커맨드 구현 | 미착수 |
| 5 | headscale DB 레포 포함 여부 결정 | 미착수 |
