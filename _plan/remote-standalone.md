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

> **headscale / step-ca 모두 shared module 아님**: 두 서비스 모두 이 서버 한 곳에서만 사용.
> `mkHostConfiguration` 내에서 직접 구현. `_preset.control-plane.toml` 별도 불필요 —
> `preset = "server"` 그대로 사용하고 나머지는 `hosts/lightsail-nixos-headscale.nix`에 직접 선언.

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
# hosts/lightsail-nixos-headscale.toml (실제 파일 기준)
preset     = "server"
type       = "server"
system     = "x86_64-linux"
username   = "ec2-user"
swapGb     = 0
tmpfsSize  = "0"
diskDevice = "/dev/nvme0n1"
bootDevice = "/dev/nvme0n1"
bootLoader = "grub-uefi"

[mods.sys.services]
caddy              = true   # headscale 443 노출용
aws-roles-anywhere = true
# headscale / step-ca는 .nix에 직접 구현 — toml 항목 없음
```

> **[deploy] 섹션이 없는 이유**: bootstrap IP/키는 1회성. 이후 서버는 독립 운영되므로
> 로컬 레포에 연결 정보를 저장할 필요가 없음.

### select_or_create_hostname() 변경

현재: `[deploy]` 섹션 있는 toml만 목록에 표시.

변경: **모든 hosts/*.toml을 하나의 플랫 리스트**로 표시.
수평선(divider) 없이 라벨로 구분 — `_pick`은 단순 번호 리스트이므로 divider가 있으면
인덱스가 꼬임.

라벨 규칙:
- `[deploy]` 섹션 있음 → IP 표시 (`1.2.3.4`) = **원격 재설치** 모드
- `[deploy]` 섹션 없음 → type 표시 (`server` / `workstation`) = **standalone bootstrap** 모드
- workstation 선택 시 RAM 최소치 경고 (`nixos-anywhere kexec` 기준)

```
호스트 선택  (IP있음=재설치 / type있음=standalone bootstrap):
  lightsail-nixos-headscale    [server]
  beelink-ser7-co              [workstation]
  msi-summit-me                [workstation]
  some-remote-server           [1.2.3.4]
+ 새 원격 호스트 추가
```

선택된 호스트의 toml에 `[deploy]` 섹션 있으면 기존 재설치 흐름,
없으면 standalone bootstrap 흐름으로 자동 분기.

### bootstrap 연결 정보 저장 (`~/.ssh/rnixup/<hostname>.bootstrap.env`)

standalone bootstrap 완료 후 IP/SSH키/유저를 별도 파일로 저장.
toml에 넣지 않되 나중에 재사용 가능 (nixstrap의 `save_params` / `load_params`와 동일 패턴).

```bash
# ~/.ssh/rnixup/<hostname>.bootstrap.env
_IP=1.2.3.4
_SSH_KEY=~/.ssh/rnixup/lightsail-nixos-headscale.pem
_SSH_USER=root
```

재실행 시 파일 있으면 "이전 bootstrap 정보 발견 — 불러올까요?" 물어보고 기본값으로 채움.

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
9. 레포 전송 (2단계):
   a. git archive HEAD | ssh root@<ip> "mkdir -p /opt/nixos && tar xf - -C /opt/nixos"
   b. scp hosts/deploy/<hostname>.hardware.nix root@<ip>:/opt/nixos/hosts/deploy/
      (git archive는 커밋된 파일만 포함 → hardware.nix는 미커밋이므로 별도 전송 필수)
10. .env 생성: ssh root@<ip> "echo NIXUP_LAST_HOST=<hostname> > /opt/nixos/.env"
    (nixup resolve_host_info가 hostname -s fallback을 쓰긴 하지만 명시적으로 생성)
11. SSH 접속 → /opt/nixos/core/scripts/nixup.sh os
    (서버에서 직접 nixos-rebuild switch, self-managed 완성)
```

> deploy-rs 없음. nixos-anywhere가 full config로 설치하고,
> 레포 전송 후 nixup os로 self-rebuild 확인.

### disko / 부트로더 안전성 분석

`nixup os` (nixos-rebuild switch) 실행 시 충돌 가능성을 검토함.

| 항목 | 결론 | 근거 |
|------|------|------|
| disko 재파티셔닝 | **안전** | `nixos-rebuild switch`는 disko를 재실행하지 않음. systemd 마운트 유닛만 갱신. |
| GRUB 재설치 | **안전** | `nixos-rebuild switch`는 grub-install을 호출하지만, `probe_disk_and_boot()`로 diskDevice가 이미 보정되어 있음. |
| `resolved.json` / `presets.json` 누락 | **안전** | git archive에 없지만 원격 `nixup os` 실행 시 `run_resolve_and_prepare`가 재생성. |
| hardware.nix 누락 | **위험** ⚠️ | `git archive HEAD`는 커밋된 파일만 포함. hardware.nix는 nixos-anywhere 이후 미커밋 상태 → **9b 단계에서 별도 scp로 해결**. |
| `.env` 미생성 | **주의** | hostname fallback이 대부분 동작하나 엣지케이스 방지를 위해 **10단계에서 명시 생성**. |

### 시크릿 주입 전략 (키파일 존재 시 자동 활성화)

서비스 모듈 내부에서 `builtins.pathExists`로 키파일 존재 여부를 평가 시점에 체크.
키파일이 없으면 서비스 config 자체가 생성되지 않으므로 실패 없이 부팅됨.

```nix
# step-ca.nix (및 headscale mkHostConfiguration)
let
  secretsReady = builtins.pathExists cfg.keyFile
              && builtins.pathExists cfg.passwordFile;
in {
  config = lib.mkIf (cfg.enable && secretsReady) {
    # ... 서비스 설정
  };
}
```

> `builtins.pathExists`는 런타임이 아닌 **nixos-rebuild 평가 시점**에 체크됨.
> 키파일이 없는 상태로 빌드하면 서비스 관련 systemd 유닛 자체가 생성되지 않음.

활성화 흐름:

```bash
# 1. 키 파일 주입
scp intermediate_ca.key root@<server>:/var/lib/step-ca-secrets/
scp ca_password         root@<server>:/var/lib/step-ca-secrets/password

# 2. 재빌드 → 키파일 감지 → 서비스 자동 포함 및 기동
ssh root@<server> /opt/nixos/core/scripts/nixup.sh os
```

Cloudflare 토큰 등 기타 시크릿도 동일 패턴.

> **구현 필요**: `step-ca.nix`에 `builtins.pathExists` 가드 추가 (현재 미적용).
> headscale은 `hosts/lightsail-nixos-headscale.nix` 직접 구현 시 동일하게 적용.

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
4. `nixup os` (재빌드) → 키파일 감지 → step-ca / headscale 자동 기동
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

## step-ca 모듈 → mkHostConfiguration 전환 계획

headscale과 동일한 이유로 step-ca도 단일 호스트에서만 사용될 경우
shared module 대신 `mkHostConfiguration` 직접 구현으로 전환 가능.

### 전환 방법

`mods/sys/services/step-ca.nix`의 내용을 `hosts/lightsail-nixos-headscale.nix`에 인라인.
`mkMod` 래퍼와 `options` 블록 제거, 값을 `let` 바인딩으로 직접 선언.

```nix
# hosts/lightsail-nixos-headscale.nix
{ mkHostConfiguration, lib, ... }:
mkHostConfiguration (_: let
  keyFile      = "/var/lib/step-ca-secrets/intermediate_ca.key";
  passwordFile = "/var/lib/step-ca-secrets/password";
  secretsReady = builtins.pathExists keyFile && builtins.pathExists passwordFile;
in {
  os = lib.mkMerge [
    # step-ca (키파일 있을 때만 활성화)
    (lib.mkIf secretsReady {
      environment.etc."step-ca/root_ca.crt".text = ''...PEM...'';
      environment.etc."step-ca/intermediate_ca.crt".text = ''...PEM...'';
      services.step-ca = {
        enable = true;
        address = "0.0.0.0";
        port = 8443;
        intermediatePasswordFile = passwordFile;
        settings = { /* 기존 step-ca.nix 그대로 */ };
      };
      systemd.services.step-ca.serviceConfig.ReadOnlyPaths = [
        (builtins.dirOf keyFile)
      ];
    })
    # headscale ...
  ];
})
```

전환 시 `_preset.control-plane.toml`에서 `step-ca = true` 플래그 제거.
`mods/sys/services/step-ca.nix` 삭제.

### 트레이드오프

| | shared module 유지 | mkHostConfiguration 전환 |
|---|---|---|
| 재사용 가능성 | ✅ 다른 서버에 적용 가능 | ❌ 인라인이므로 복붙 필요 |
| 구현 일관성 | headscale과 다름 | headscale과 동일 방식 |
| 코드 복잡도 | options 정의 오버헤드 | 직접 선언으로 단순 |
| builtins.pathExists 가드 | module 내부에 추가 필요 | let 바인딩으로 자연스럽게 |

> **결정 기준**: 다른 서버에 step-ca를 추가할 계획이 없으면 전환.
> 있으면 module에 `builtins.pathExists` 가드만 추가하고 유지.

---

## 구현 우선순위

| 순서 | 작업 | 상태 |
|------|------|------|
| 1 | `mods/sys/services/step-ca.nix` (기본 구현) | ✅ 완료 |
| 2 | `aws-roles-anywhere.nix` caServer/caCert 옵션 | ✅ 완료 |
| 3 | `_preset.server.toml` SSH 명시 | 미착수 |
| 4 | `mods/sys/services/step-ca.nix` 삭제 + mkHostConfiguration 인라인 전환 | 미착수 |
| 5 | `rnixstrap` standalone 호스트 지원 확장 | 미착수 |
| 6 | `hosts/lightsail-nixos-headscale.nix` headscale + step-ca 직접 구현 (builtins.pathExists 가드 포함) | 미착수 |
