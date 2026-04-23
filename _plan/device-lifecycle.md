# 직원 기기 라이프사이클 관리

## 목표

- 등록 시 자동 환경 세팅 (macOS: nix + tailscale / iOS·Android: tailscale)
- 퇴사/반납 시 업무 워크스페이스만 제거 (개인 데이터 보존)
- 기기 분실/도난 시 원격 초기화
- 직원 간섭 최소화 — 감시·제한 없음

## 대응 기기

| 기기 | MDM | 비고 |
|------|-----|------|
| macOS | NanoMDM | nix + tailscale 자동 설치 |
| iOS (iPhone / iPad) | NanoMDM | tailscale만 (nix 없음) |
| Android | Headwind MDM | Work Profile + tailscale |

---

## 1. 전제 조건

### 서버

Lightsail 4GB — 기존 서버 업그레이드 후 아래 서비스 추가.

### 전체 서비스 구성

```
lightsail-nixos-headscale (4GB)
├── Caddy              — reverse proxy / HTTPS
├── step-ca            — 내부 CA / ACME
├── headscale          — VPN (Google Workspace OIDC)  [e.772610158.xyz]
├── MySQL              — 공유 DB (NanoMDM + Headwind + Passbolt + Dashboard)
├── NanoMDM            — macOS / iOS MDM              [apple.m.772610158.xyz]
├── Headwind MDM       — Android MDM                  [android.m.772610158.xyz]
├── Passbolt           — 패스워드 매니저              [passbolt.i.772610158.xyz]
└── 대시보드 (Node)    — 관리 UI                      [mdm.i.772610158.xyz]
```

### 도메인

| 서비스 | 도메인 | 접근 |
|--------|--------|------|
| headscale | `e.772610158.xyz` | 공개 (기기 tailnet 참여) |
| NanoMDM | `apple.m.772610158.xyz` | 공개 (기기 체크인) |
| Headwind MDM | `android.m.772610158.xyz` | 공개 (기기 체크인) |
| 대시보드 | `mdm.i.772610158.xyz` | tailscale 내부망 전용 |
| Passbolt | `passbolt.i.772610158.xyz` | tailscale 내부망 전용 |

### 스택

| 역할 | 선택 | 배포 방식 |
|------|------|-----------|
| NanoMDM | Go 바이너리 | NixOS 네이티브 (`buildGoModule`) |
| Headwind MDM | Java/Spring Boot | `oci-containers` (podman, digest 고정) |
| Passbolt | PHP | `oci-containers` (podman, digest 고정) |
| MySQL | 공유 DB | `services.mysql` (NixOS 네이티브) |
| 대시보드 | Node + Hono + HTMX | PoC: `apps/mdm-dashboard/` → 이후 별도 레포 |

### MySQL 공유 DB

```nix
services.mysql = {
  enable = true;
  package = pkgs.mysql80;
  ensureDatabases = [ "nanomdn" "headwind" "passbolt" "mdm_dashboard" ];
  ensureUsers = [
    # 네이티브 서비스 (NanoMDM, 대시보드): 소켓 인증 — 패스워드 불필요
    { name = "nanomdn";   ensurePermissions = { "nanomdn.*"       = "ALL PRIVILEGES"; }; }
    { name = "dashboard"; ensurePermissions = { "mdm_dashboard.*" = "ALL PRIVILEGES"; }; }
    # oci-containers (Headwind, Passbolt): host.containers.internal TCP 접속
    # TODO: TCP 접속용 패스워드 설정 필요 — ensureUsers는 소켓 인증만 생성함.
    #       구현 시 initialScript 또는 secrets로 ALTER USER 처리 필요.
    { name = "headwind";  ensurePermissions = { "headwind.*"      = "ALL PRIVILEGES"; }; }
    { name = "passbolt";  ensurePermissions = { "passbolt.*"      = "ALL PRIVILEGES"; }; }
  ];
};
```

### headscale OIDC (Google Workspace)

Proxmox 기존 설정값을 NixOS로 이전. 기기-직원 매핑의 기반.

### NanoMDM 서비스

```nix
# 사전 요구사항:
# - /var/lib/nanomdn-secrets/apns.pem  (APNs 인증서, 연 1회 갱신)
# - /var/lib/apple-secrets/cert.pem    (코드서명 인증서)
# - /var/lib/apple-secrets/key.pem
services.nanomdn = {
  enable = true;
  storage = "mysql";
  dsn = "nanomdn:password@/nanomdn";
  apnsCert = "/var/lib/nanomdn-secrets/apns.pem";
};
```

```
apple.m.772610158.xyz {
    reverse_proxy * localhost:9000
}
```

### Headwind MDM

```nix
# 사전 요구사항:
# - Google Workspace Android Enterprise 연동
#   (Google Cloud Console → Android Management API 활성화)
virtualisation.oci-containers.containers.headwind = {
  image = "headwindmdm/headwind@sha256:<digest>";
  ports = [ "31337:31337" ];
  volumes = [ "/var/lib/headwind:/data" ];
  environment = { DB_HOST = "host.containers.internal"; DB_NAME = "headwind"; };
};
```

```
android.m.772610158.xyz {
    reverse_proxy * localhost:31337
}
```

### Passbolt

```nix
# 사전 요구사항:
# - /var/lib/passbolt-secrets/admin.gpg  (관리자 GPG 키)
# - /var/lib/passbolt-secrets/server.key (서버 GPG 키)
virtualisation.oci-containers.containers.passbolt = {
  image = "passbolt/passbolt@sha256:<digest>";
  ports = [ "8080:80" ];
  environment = { DB_HOST = "host.containers.internal"; DB_NAME = "passbolt"; };
  volumes = [ "/var/lib/passbolt-secrets:/etc/passbolt/gpg:ro" ];
};
```

```
passbolt.i.772610158.xyz {
    reverse_proxy * localhost:8080
}
```

---

## 2. 온보딩 — 기기 등록

### 흐름

```
IT: 대시보드에서 직원 email 입력 → 고유 enrollment 토큰 생성
  → 직원에게 링크 전달 (이메일/슬랙)

직원: 링크 클릭 → Google 로그인 (company.com)
  → .mobileconfig 다운로드 (Apple) / HMDC 앱 QR 스캔 (Android)
  → 기기 등록 완료

대시보드 DB: 기기 ID ↔ Google email 매핑 자동 저장
headscale: 같은 Google 계정으로 tailnet 참여
```

### macOS enrollment profile

`.mobileconfig` — Apple Developer 인증서로 서명 (미서명 시 "확인되지 않음" 경고):

```bash
openssl smime -sign \
  -in profile.mobileconfig \
  -out signed.mobileconfig \
  -signer /var/lib/apple-secrets/cert.pem \
  -inkey /var/lib/apple-secrets/key.pem \
  -outform der -nodetach
```

```xml
<key>ServerURL</key>  <string>https://apple.m.772610158.xyz/mdm</string>
<key>CheckInURL</key> <string>https://apple.m.772610158.xyz/checkin</string>
```

### macOS 자동 설치 스크립트

NanoMDM `InstallCommand`로 1회 실행:

```bash
#!/usr/bin/env bash
set -euo pipefail

# Nix (Determinate Systems — MDM 환경 안정적)
curl --proto '=https' --tlsv1.2 -sSf \
    https://install.determinate.systems/nix | sh -s -- install --no-confirm

# Tailscale — nix로 설치 (brew 불필요)
# TODO: macOS에서 VPN system extension 동작 여부 테스트 필요.
#       미동작 시 App Store InstallApplication으로 전환 (iOS와 동일 방식)
nix profile install nixpkgs#tailscale

# headscale 연결 (pre-auth key는 MDM 파라미터로 주입)
tailscale up \
    --login-server=https://e.772610158.xyz \
    --authkey=<preauth-key> \
    --hostname="$(scutil --get ComputerName)"
```

headscale pre-auth key: `headscale preauthkeys create --reusable --expiration 0`

### iOS 자동 설치

> `com.tailscale.ipn.loginURL` MDM 키 실제 지원 여부 미검증.
> `mkIf` 분기로 구현, 테스트 후 활성화.

```json
{ "RequestType": "InstallApplication", "iTunesStoreID": 1470499037 }
```
<!-- TODO: App Store ID 1470499037 실제 Tailscale iOS 앱 ID 여부 배포 전 반드시 확인 필요 -->

```xml
<!-- enrollment profile에 포함 (지원 확인 후 활성화) -->
<key>com.tailscale.ipn.loginURL</key>
<string>https://e.772610158.xyz</string>
```

### Android 자동 설치 (Work Profile)

Headwind MDM enrollment → HMDC 앱 → Work Profile 생성 → Tailscale APK 배포:

```bash
tailscale up \
    --login-server=https://e.772610158.xyz \
    --authkey=<preauth-key> \
    --hostname="$(getprop net.hostname)"
```

Work Profile 내 앱은 개인 앱과 독립 실행 — 개인 계정과 충돌 없음.

---

## 3. 운영

### 대시보드 (mdm.i.772610158.xyz)

**인증**: tailscale ACL (관리자 기기/계정만), 공수 과다 시 토큰 로그인 fallback.

**기능**:
- 직원 목록 + 기기 목록 (Google email 기준 그룹)
- 기기당 상태 (마지막 체크인, OS, 기기명)
- enrollment 링크 / QR 생성
- 오프보딩 액션 (아래 섹션 참고)

**백엔드 연동**:
- NanoMDM REST API
- Headwind MDM REST API
- Passbolt Admin API (`/var/lib/passbolt-secrets/admin.gpg` GPG 인증)
- headscale API

**위치**: PoC → `apps/mdm-dashboard/` (이 레포) → 검증 후 별도 레포

### Passbolt

GPG 키 기반 — 마스터 패스워드 없음, 브라우저 익스텐션이 복호화.
퇴사자 대응: GPG 키 폐기로 즉시 접근 차단.

### MDM 체크인

| 서비스 | 체크인 주기 | 비고 |
|--------|------------|------|
| NanoMDM | 기기별 설정 (기본 24h) | APNs 푸시로 즉시 깨울 수 있음 |
| Headwind MDM | 기기별 설정 | FCM 푸시 |

---

## 4. 오프보딩

### 퇴사 / 반납 — 통합 처리 버튼

대시보드에서 직원 단위로 1회 처리:

| 단계 | 액션 | API |
|------|------|-----|
| 1 | MDM 워크스페이스 제거 | NanoMDM: 프로파일 해제 / Headwind: `DELETE_WORK_PROFILE` |
| 2 | Passbolt GPG 키 폐기 | Passbolt Admin API |
| 3 | headscale 노드 제거 | headscale API |

2-step 확인 필수. 개인 데이터는 보존.

### 분실 / 도난 — 원격 초기화

```nix
# ABM Supervised 등록 완료 전까지 비활성화
# lightsail-nixos-headscale.nix
mkIf config.services.nanomdn.abmEnabled {
  # EraseDevice 커맨드 활성화
}
```

| 기기 | 커맨드 | 조건 |
|------|--------|------|
| macOS / iOS | `EraseDevice` | ABM Supervised 필요 (mkIf) |
| Android | `WIPE` | 즉시 사용 가능 |

원격 초기화: 2-step 확인 + 사유 입력 필수.

---

## 5. 백업 / 유지보수

### MySQL S3 백업

IAM Roles Anywhere 설정 완료 후 진행 (전제: Roles Anywhere 가동 중).

```bash
# systemd timer (매일)
mysqldump --all-databases \
  | gzip \
  | aws s3 cp - s3://<bucket>/mysql/$(date +%Y%m%d).sql.gz

# 시크릿 파일 동기화
aws s3 sync /var/lib/nanomdn-secrets  s3://<bucket>/secrets/nanomdn/
aws s3 sync /var/lib/passbolt-secrets s3://<bucket>/secrets/passbolt/
aws s3 sync /var/lib/apple-secrets    s3://<bucket>/secrets/apple/
```

### APNs 인증서 갱신

연 1회 수동 갱신. 만료 30일 전 알림 (로드맵 참고).

---

## 6. 구현 순서

| 순서 | 작업 | 상태 |
|------|------|------|
| 1 | Lightsail 4GB 업그레이드 | 미착수 |
| 2 | headscale OIDC (Google Workspace) NixOS 이전 | 미착수 |
| 3 | MySQL (services.mysql) 세팅 + 공유 DB 구성 | 미착수 |
| 4 | NanoMDM NixOS 서비스 패키징 | 미착수 |
| 5 | Apple enrollment profile 작성 + 서명 | 미착수 |
| 6 | macOS 자동 설치 스크립트 | 미착수 |
| 7 | iOS 자동 설치 (mkIf) | 미착수 |
| 8 | Headwind MDM oci-containers | 미착수 |
| 9 | Android Work Profile + tailscale | 미착수 |
| 10 | Passbolt oci-containers | 미착수 |
| 11 | 대시보드 PoC (`apps/mdm-dashboard/`) | 미착수 |
| 12 | S3 백업 자동화 | 미착수 |

---

## 7. 로드맵

### ABM (Apple Business Manager) 등록

가입 후 Supervised 모드 활성화 → `EraseDevice` mkIf 조건 해제.

### APNs 인증서 갱신 알림 자동화

```bash
# systemd timer로 매일 체크
days_left=$(( ( $(date -d "$(openssl x509 -enddate -noout -in \
  /var/lib/nanomdn-secrets/apns.pem | cut -d= -f2)" +%s) \
  - $(date +%s) ) / 86400 ))
[ "$days_left" -lt 30 ] && notify "APNs 인증서 ${days_left}일 후 만료"
```

알림 채널: 이메일 + 슬랙 봇 (채널 미정, 플레이스홀더).

### 대시보드 별도 레포 분리

PoC 검증 후 독립 레포로 이전.

---

## 보안 요약

| 항목 | 방법 |
|------|------|
| 대시보드 접근 | tailscale ACL (관리자만) |
| headscale pre-auth key | MDM 스크립트 파라미터 주입, 소스 미포함 |
| APNs 인증서 | `/var/lib/nanomdn-secrets/` 파일 주입 |
| Apple 코드서명 인증서 | `/var/lib/apple-secrets/` 파일 주입 |
| Passbolt 관리자 GPG 키 | `/var/lib/passbolt-secrets/` 파일 주입 |
| 워크스페이스 제거 | 2-step 확인 |
| 원격 초기화 | 2-step 확인 + 사유 입력 필수 |
| `EraseDevice` | ABM 등록 완료 후 mkIf 활성화 |
