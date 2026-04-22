# 원격 스탠드얼론 서버 부트스트랩 계획

## 개요

NixOS 레포 자체를 원격 서버에 1회성으로 전달해 완전히 자립적인(standalone)
관리 서버를 만드는 기능. 이후 해당 서버는 로컬 `nixup os`와 동일하게 자기 자신을
직접 관리하는 독립 NixOS 서버가 된다.

---

## 컨트롤 플레인 서버 구성

한 대의 서버에 아래 세 역할을 집약한다.

| 역할 | 구현 위치 | 비고 |
|------|-----------|------|
| Tailscale 코디네이터 | `hosts/lightsail-nixos-headscale.nix` (mkHostConfiguration 직접) | 인터넷 노출 필수, 재사용 불필요 |
| 사설 CA | `mods.sys.services.step-ca` ✅ 완료 | tailnet + 인터넷 양쪽 접근 가능 |
| Nix 바이너리 캐시 프록시 | `mods.sys.services.nix-cache-proxy` ✅ 완료 | tailnet 내부 전용 |

프리셋: `_preset.control-plane.toml`

> **headscale이 shared module이 아닌 이유**: headscale은 이 서버 한 곳에서만 사용되므로
> `mkHostConfiguration` 내에서 직접 구현. 여러 곳에서 재사용할 서비스가 아님.

### headscale + step-ca 동거 이유

- headscale 서버는 어차피 인터넷에 노출 → CA도 별도 공개 IP 없이 인터넷에서 도달 가능
  → tailnet 합류 전 신규 서버도 CA에 직접 접근 가능.
- 이 서버가 살아있으면 나머지 모든 인프라가 동작하는 구조 → 의존성 체인이 단순하고 명확.
- 단일 장애점(SPOF) 문제는 키 백업 + 빠른 재부트스트랩으로 수용 가능한 리스크.
  (기존 인증서는 유효 기간 동안 계속 동작, headscale 재등록만 처리하면 됨)

---

## rnixstrap standalone 확장 설계

### 핵심 방향

별도 커맨드(`nixup remote-bootstrap`) 없이 **rnixstrap을 확장**한다.
"로컬 워크스테이션에 nixstrap으로 설치하는 것처럼, 원격지에 NixOS를 밀어넣는다"는
개념이 동일하기 때문.

### 기존 rnixstrap과의 차이

| | 기존 rnixstrap (원격 재배포) | standalone bootstrap |
|---|---|---|
| 호스트 조건 | `[deploy]` 섹션 있는 toml | `[deploy]` 섹션 **없는** toml |
| toml 구조 | ip/sshKey 저장됨 | 로컬 호스트와 동일 구조, ip/key는 bootstrap 시에만 임시 사용 |
| 최종 배포 | deploy-rs (로컬에서 push) | 레포 전송 후 서버에서 `nixup os` (self-rebuild) |
| 이후 관리 | `rnixup`으로 원격 push | 서버에서 직접 `nixup os` (독립 서버) |

### standalone 호스트 toml 구조

로컬 호스트(nixstrap)와 동일한 구조. `[deploy]` 섹션 없음. 추가 필드 불필요.

```toml
# 예: hosts/lightsail-nixos-headscale.toml (현재 구조 그대로)
preset     = "control-plane"
type       = "server"
system     = "x86_64-linux"
swapGb     = 0
tmpfsSize  = "0"
diskDevice = "/dev/nvme0n1"
bootDevice = "/dev/nvme0n1"
bootLoader = "grub-uefi"

[mods.sys.services]
headscale          = true
step-ca            = true
nix-cache-proxy    = true
```

> **[deploy] 섹션이 없는 이유**: bootstrap IP/키는 1회성. 이후 서버는 독립 운영되므로
> 로컬 레포에 연결 정보를 저장할 필요가 없음.

### select_or_create_hostname() 변경

현재: `[deploy]` 섹션 있는 toml만 목록에 표시.

변경:
- `[deploy]` 섹션 없는 toml도 "standalone bootstrap" 대상으로 표시
- type(workstation/server) 함께 표시
- workstation 선택 시 RAM 최소치 경고 (`nixos-anywhere kexec` 기준)
- ip/key는 대화형으로 입력, **toml에 저장하지 않음** (bootstrap 세션 내 임시 사용)

```
호스트 선택:
  > lightsail-nixos-headscale    [server]   ← standalone bootstrap
    beelink-ser7-co              [workstation] ← RAM 경고 표시
  + 새 원격 호스트 추가
────────────────────────────────
  (기존 원격 호스트 — 재설치)
    some-remote-server           [1.2.3.4]
```

### standalone bootstrap 실행 흐름

```
1. 호스트 선택 (deploy 섹션 없는 toml)
2. IP / SSH키 입력 (임시, toml 미저장)
3. probe SSH + RAM 확인
4. probe disk/boot → toml의 diskDevice/bootLoader 업데이트
5. extract pub key → hosts/deploy/<hostname>.pub 저장
6. resolve + prepare BUILD_DIR
7. nixos-anywhere --flake BUILD_DIR#<hostname>
   (hardware.nix 자동 생성 → hosts/deploy/<hostname>.hardware.nix 저장)
8. wait_for_ssh (재부팅 대기)
9. 레포 전송: git archive HEAD | ssh root@<ip> "tar xf - -C /opt/nixos"
   (hosts/deploy/ git tracked이므로 hardware.nix 포함됨)
10. SSH 접속 → /opt/nixos/core/scripts/nixup.sh os
    (서버에서 직접 nixos-rebuild switch, self-managed 완성)
```

> deploy-rs 없음. nixos-anywhere가 full config로 설치하고,
> 레포 전송 후 nixup os로 self-rebuild 확인.

### 시크릿 주입 전략 (수동 활성화)

bootstrap 완료 직후 서비스들(step-ca, headscale)은 시크릿 파일 부재로 시작 실패 상태.
서비스 활성화는 별도 수동 작업:

```bash
# 1. 키 파일 주입
scp intermediate_ca.key root@<server>:/var/lib/step-ca-secrets/
scp ca_password         root@<server>:/var/lib/step-ca-secrets/password

# 2. 서비스 활성화
ssh root@<server> systemctl restart step-ca
ssh root@<server> systemctl restart headscale
```

Cloudflare 토큰 등 기타 시크릿도 동일 패턴.

---

## _preset.server.toml SSH 보강

현재 `_preset.server.toml`에 SSH 설정이 명시적으로 없음. standalone 서버는
bootstrap 이후 SSH가 유일한 접근 수단이므로 프리셋에 명시 필요:

- `services.openssh.enable = true`
- 패스워드 인증 비활성화
- `authorizedKeys`는 bootstrap 시 rnixstrap이 `hosts/deploy/<hostname>.pub`에서 주입

---

## 키 백업 전략

컨트롤 플레인 서버에서 외부 보관이 필요한 시크릿:

| 파일 | 저장 위치 | 권한 |
|------|----------|------|
| `intermediate_ca.key` | passbolt / vaultwarden | 644 (암호화된 키) |
| `password` (CA 키 패스워드) | passbolt / vaultwarden | 600 |
| headscale private key | passbolt / vaultwarden | 600 |
| `~/.ssh/rnixup/*.pem` | 로컬 + passbolt | 600 |

### headscale DB 백업

headscale DB는 개인정보(노드 등록 정보)를 포함하므로 git 레포에 포함하지 않음.
주기적 수동 백업 (passbolt 또는 별도 오브젝트 스토리지).

복구 시 DB 없으면 기존 tailnet 노드들 재등록 필요.

### 복구 시나리오

서버가 완전히 날아간 경우:
1. 새 서버 프로비저닝 (Lightsail 콘솔)
2. `rnixstrap` → `lightsail-nixos-headscale` 선택 → IP/키 입력 → standalone bootstrap
3. passbolt에서 키 파일 복원 → `/var/lib/step-ca-secrets/` 주입
4. `systemctl restart step-ca headscale`
5. headscale DB 복원 → tailnet 노드 자동 재연결 (DB 없으면 재등록)

목표 복구 시간: **30분 이내**

---

## 부트스트랩 의존성 체인

```
[1] rnixstrap standalone → 컨트롤 플레인 서버 (headscale + step-ca + nix-cache)
         ↓
[2] 시크릿 수동 주입 → step-ca / headscale 서비스 활성화
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
| 1 | `mods/sys/services/step-ca.nix` | ✅ 완료 |
| 2 | `aws-roles-anywhere.nix` caServer/caCert 옵션 | ✅ 완료 |
| 3 | `_preset.server.toml` SSH 명시 | 미착수 |
| 4 | `_preset.control-plane.toml` 정의 | 미착수 |
| 5 | `rnixstrap` standalone 호스트 지원 확장 | 미착수 |
| 6 | `hosts/lightsail-nixos-headscale.nix` headscale 직접 구현 | 미착수 |
