# rnixup / rnixstrap 명령어 레퍼런스

원격 NixOS 호스트의 **배포**(`rnixup`)와 **초기 설치**(`rnixstrap`)를 담당하는 도구입니다.

> 상황별 활용 사례는 [시스템 관리](../how-to/manage-system.md) 참조  
> 시크릿 관리(nixsec)는 [nixsec 명령어](./nixsec-commands.md) 참조

---

## rnixup

`hosts/*.toml`에 `[deploy]` 섹션이 있는 호스트에 변경 사항을 배포합니다.

### 기본 구조

```bash
rnixup [hostname] [flags]
```

`hostname`을 생략하면 `[deploy]` 섹션이 있는 모든 호스트에 배포합니다.

### 플래그

| 명령 / 플래그 | 동작 |
|---|---|
| `rnixup` | dry-activate → 사용자 확인 → 시크릿 자동 주입 → deploy-rs 배포 |
| `rnixup <hostname>` | 특정 호스트만 배포 |
| `rnixup --dry-run-only` | dry-activate 결과만 출력하고 즉시 종료 (확인/주입/배포 없음) |
| `rnixup --apply-only` | dry-activate · 사용자 확인 없이 시크릿 주입 + 배포만 실행 |
| `rnixup list` | 등록된 원격 호스트 목록 출력 |

플래그와 hostname을 함께 사용할 수 있습니다:

```bash
rnixup headscale-vps --dry-run-only
rnixup headscale-vps --apply-only
```

### 시크릿 자동 주입

배포 시 `hosts/_deploy/<hostname>.secrets/secrets.json`에 정의된 시크릿을 자동으로 처리합니다.

- 서버의 기존 파일과 **SHA256 해시 비교** → 변경된 파일만 전송
- 변경 없는 파일은 `Skip: 변경 없음` 메시지와 함께 건너뜀
- SSH 해시 확인 실패 시 전체 전송으로 안전하게 fallback

:::note
이 동작은 `--dry-run-only` 실행 시에는 발생하지 않습니다.
:::

---

## rnixstrap

원격 서버에 nixos-anywhere로 NixOS를 **처음 설치**할 때 사용합니다. 완료 후 일상 배포는 `rnixup`을 사용합니다.

### 기본 구조

```bash
rnixstrap [--hostname HOST] [--write-only]
```

### 모드

**대화형 모드 (기본):**

```bash
rnixstrap
```

서버 IP, SSH 키, 서비스 구성을 대화형으로 입력합니다.

**비대화형 모드:**

```bash
rnixstrap --hostname HOST
```

`~/.ssh/rnixup/<hostname>.strap.json` 또는 기존 TOML에서 설정을 자동으로 로드합니다.

```bash
rnixstrap --hostname HOST --write-only
```

파일 작업(TOML · `.nix` 생성)만 수행하고 실제 설치 없이 종료합니다.

### 설정 로드 우선순위 (비대화형)

| 우선순위 | 소스 | 적용 조건 |
|---------|------|---------|
| 1 | `~/.ssh/rnixup/<hostname>.strap.json` | 파일 존재 시 |
| 2 | `hosts/<hostname>.toml` | 기존 호스트(`[deploy]` 있음) |
| 3 | `~/.ssh/rnixup/<hostname>.bootstrap.env` | standalone 호스트 |

신규 호스트에서 `ip` 또는 `sshKey`가 없으면 에러로 종료합니다.

### `.strap.json` 형식

`~/.ssh/rnixup/<hostname>.strap.json` 에 저장합니다. (기계별 로컬 파일, git 비추적)

```json
{
  "ip": "1.2.3.4",
  "sshKey": "~/.ssh/rnixup/hostname.pem",
  "sshUser": "root",
  "system": "x86_64-linux",
  "bootLoader": "grub-uefi",
  "diskDevice": "/dev/vda",
  "services": ["caddy", "docker"],
  "writeOnly": false
}
```

| 필드 | 필수 | 기본값 | 설명 |
|------|:----:|--------|------|
| `ip` | 신규만 | — | 서버 공인 IP |
| `sshKey` | 신규만 | — | SSH 개인키 경로 (`~` 확장 지원) |
| `sshUser` | ✗ | `root` | bootstrap 접속 유저 |
| `system` | ✗ | `x86_64-linux` | 아키텍처 (`aarch64-linux` 가능) |
| `bootLoader` | ✗ | 자동 감지 | `grub-bios` / `grub-uefi` |
| `diskDevice` | ✗ | 자동 감지 | 대상 디스크 (`/dev/vda` 등) |
| `services` | ✗ | `[]` | 활성화할 서비스 목록 |
| `writeOnly` | ✗ | `false` | `true`면 파일 작업만 수행 |

`bootLoader`와 `diskDevice`를 생략하면 SSH로 서버에 접속하여 자동 감지합니다.

:::note
`sshPass` 필드로 비밀번호 인증도 지원합니다. 비밀번호 방식에서는 `sshKey`를 NixOS 설치 후 접속용 deploy key로 사용합니다.
:::
