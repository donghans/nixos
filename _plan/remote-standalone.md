# 원격 스탠드얼론 서버 부트스트랩 계획

## 구현 우선순위

| 순서 | 작업 | 상태 |
|------|------|------|
| — | `mods/sys/services/step-ca.nix` 기본 구현 | ✅ 완료 |
| — | `aws-roles-anywhere.nix` caServer/caCert 옵션 | ✅ 완료 |
| 1 | `_preset.server.toml` SSH 명시 | 미착수 |
| 2 | `mods/sys/services/step-ca.nix` 삭제 + `lightsail-nixos-headscale.nix` 인라인 전환 | 미착수 |
| 3 | `hosts/lightsail-nixos-headscale.nix` headscale + step-ca 직접 구현 | 미착수 |
| 4 | `rnixstrap` standalone 호스트 지원 확장 | 미착수 |

---

## 1. `_preset.server.toml` SSH 보강

`services.openssh` 관련 설정이 현재 누락되어 있음. standalone 서버는 SSH가 유일한 접근 수단.

추가할 내용:
- `services.openssh.enable = true`
- `services.openssh.settings.PasswordAuthentication = false`
- `authorizedKeys`는 rnixstrap이 bootstrap 시 `hosts/deploy/<hostname>.pub`에서 주입

---

## 2 & 3. `hosts/lightsail-nixos-headscale.nix` 구현

`mods/sys/services/step-ca.nix` 삭제 후 headscale + step-ca를 `mkHostConfiguration`에 직접 인라인.
`builtins.pathExists`로 키파일 존재 여부를 평가 시점에 체크 — 없으면 서비스 유닛 자체 미생성.

```nix
{ mkHostConfiguration, lib, ... }:
mkHostConfiguration (_: let
  keyFile      = "/var/lib/step-ca-secrets/intermediate_ca.key";
  passwordFile = "/var/lib/step-ca-secrets/password";
  secretsReady = builtins.pathExists keyFile && builtins.pathExists passwordFile;
in {
  os = lib.mkMerge [
    (lib.mkIf secretsReady {
      environment.etc."step-ca/root_ca.crt".text = ''...PEM...'';
      environment.etc."step-ca/intermediate_ca.crt".text = ''...PEM...'';
      services.step-ca = {
        enable = true;
        address = "0.0.0.0";
        port = 8443;
        intermediatePasswordFile = passwordFile;
        settings = { /* 기존 step-ca.nix settings 그대로 */ };
      };
      systemd.services.step-ca.serviceConfig.ReadOnlyPaths = [
        (builtins.dirOf keyFile)
      ];
    })
    {
      # headscale 설정
    }
  ];
})
```

시크릿 주입 후 `nixup os` 재빌드하면 서비스 자동 활성화:
```bash
scp intermediate_ca.key root@<server>:/var/lib/step-ca-secrets/
scp ca_password         root@<server>:/var/lib/step-ca-secrets/password
ssh root@<server> /opt/nixos/core/scripts/nixup.sh os
```

---

## 4. rnixstrap standalone 확장

### select_or_create_hostname() 변경

모든 `hosts/*.toml`을 하나의 플랫 리스트로 표시. `[deploy]` 섹션 유무로 모드 자동 분기.

- `[deploy]` 섹션 있음 → IP 표시 → **재설치** 모드 (기존 흐름)
- `[deploy]` 섹션 없음 → type 표시 → **standalone bootstrap** 모드
- workstation 선택 시 nixos-anywhere kexec RAM 최소치 경고

```
호스트 선택:
  lightsail-nixos-headscale    [server]
  beelink-ser7-co              [workstation]
  some-remote-server           [1.2.3.4]
+ 새 원격 호스트 추가
```

### bootstrap 연결 정보 저장

완료 후 `~/.ssh/rnixup/<hostname>.bootstrap.env` 저장. 재실행 시 불러오기 제안 (nixstrap `save_params` / `load_params`와 동일 패턴).

```bash
_IP=1.2.3.4
_SSH_KEY=~/.ssh/rnixup/lightsail-nixos-headscale.pem
_SSH_USER=root
```

### 실행 흐름

```
1.  호스트 선택 (deploy 섹션 없는 toml)
2.  IP / SSH키 입력  (bootstrap.env 있으면 기본값 제안)
3.  probe SSH + RAM 확인
4.  probe disk/boot → toml diskDevice/bootLoader 업데이트
5.  extract pub key → hosts/deploy/<hostname>.pub 저장
6.  resolve + prepare BUILD_DIR
7.  nixos-anywhere --flake BUILD_DIR#<hostname>
    └─ hardware.nix 생성 → hosts/deploy/<hostname>.hardware.nix
8.  wait_for_ssh (재부팅 대기)
9.  레포 전송:
    a. git archive HEAD | ssh root@<ip> "mkdir -p /opt/nixos && tar xf - -C /opt/nixos"
    b. scp hosts/deploy/<hostname>.hardware.nix root@<ip>:/opt/nixos/hosts/deploy/
       ※ git archive는 미커밋 파일 미포함 → hardware.nix 별도 전송 필수
10. ssh root@<ip> "echo NIXUP_LAST_HOST=<hostname> > /opt/nixos/.env"
11. ssh root@<ip> /opt/nixos/core/scripts/nixup.sh os
12. ~/.ssh/rnixup/<hostname>.bootstrap.env 저장
```

### 안전성

| 항목 | 결론 |
|------|------|
| disko 재파티셔닝 | 안전 — nixos-rebuild switch는 disko 재실행 안 함 |
| GRUB 재설치 | 안전 — probe_disk_and_boot()로 diskDevice 보정됨 |
| resolved.json / presets.json 누락 | 안전 — nixup os 실행 시 run_resolve_and_prepare가 재생성 |
| hardware.nix 미커밋 | 9b 단계에서 별도 scp로 해결 |
| .env 미생성 | 10단계에서 명시 생성 |

---

## 키 백업 및 복구

| 파일 | 저장 위치 | 권한 |
|------|----------|------|
| `intermediate_ca.key` | passbolt / vaultwarden | 644 |
| `password` (CA 키) | passbolt / vaultwarden | 600 |
| headscale private key | passbolt / vaultwarden | 600 |
| `~/.ssh/rnixup/*.pem` | 로컬 + passbolt | 600 |

headscale DB: git 미포함. 주기적 수동 백업. 복구 시 DB 없으면 tailnet 노드 재등록 필요.

### 복구 시나리오 (목표 30분 이내)

1. 새 서버 프로비저닝 (Lightsail 콘솔)
2. `rnixstrap` → `lightsail-nixos-headscale` 선택 → IP/키 입력 → standalone bootstrap
3. passbolt에서 키 파일 복원 → `/var/lib/step-ca-secrets/` 주입
4. `nixup os` → step-ca / headscale 자동 기동
5. headscale DB 복원 → tailnet 노드 재연결

---

## 부트스트랩 의존성 체인

```
[1] rnixstrap standalone → 컨트롤 플레인 (headscale + step-ca)
         ↓
[2] 시크릿 주입 + nixup os → 서비스 활성화
         ↓
[3] 신규 서버 rnixstrap → tailnet 합류
         ↓
[4] step-ca ACME → 인증서 발급
         ↓
[5] aws-roles-anywhere → AWS 임시 자격증명
         ↓
[6] SSM Session Manager
```
