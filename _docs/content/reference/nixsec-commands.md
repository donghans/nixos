# nixsec 명령어 레퍼런스

`nixsec`은 age 암호화 기반 시크릿 관리 도구입니다. GitHub 비공개 레포에 시크릿을 암호화해서 저장하고, 원격 호스트에 복호화하여 주입합니다.

> 원격 배포/설치 명령어는 [rnixup/rnixstrap 명령어](./rnixup-commands.md) 참조

---

## 대화형 모드

```bash
nixsec
```

메뉴에서 작업을 선택합니다:

| 선택 | 동작 |
|------|------|
| 새 레포 초기화 | age 키 생성 + GitHub 프라이빗 레포 생성 |
| 시크릿 업로드 | 파일을 age 암호화해서 레포에 추가/갱신 |
| 원격 호스트에 주입 | 워크스테이션에서 복호화 후 SSH 전송 |
| 이 워크스테이션에 적용 | secrets.json 기반으로 로컬에 복호화 배치 |
| age 키 복구 | 새 워크스테이션에서 키 경로 등록 |

---

## 비대화형 모드

서브커맨드로 비대화형 실행이 가능합니다.

:::caution
**전부 채우거나 아무것도 채우지 않아야 합니다.** 파라미터가 하나라도 있으면 나머지도 모두 필요합니다. 일부만 있으면 에러로 종료합니다.
:::

### `nixsec upload` — 시크릿 업로드

```bash
nixsec upload \
  --repo OWNER/REPO \
  --group GROUP \
  --remote-path PATH \
  --file FILE
```

또는 stdin에서 읽기:

```bash
cat secret.txt | nixsec upload \
  --repo OWNER/REPO \
  --group GROUP \
  --remote-path PATH \
  --stdin
```

| 파라미터 | 설명 |
|---------|------|
| `--repo` | GitHub 레포 (예: `BITSTEP-IT/my-secrets`) |
| `--group` | secrets.json의 그룹명 |
| `--remote-path` | 레포 내 경로 (`.age` 확장자 제외, 예: `hostname/headscale/key`) |
| `--file` | 업로드할 로컬 파일 경로 |
| `--stdin` | `--file` 대신 stdin에서 내용 읽기 |

### `nixsec inject` — 원격 호스트에 주입

```bash
nixsec inject --hostname HOST
```

`hosts/_deploy/<hostname>.secrets/secrets.json`의 모든 그룹을 자동 선택하여 주입합니다. 특정 그룹만 주입하려면 `--group`을 지정합니다:

```bash
nixsec inject --hostname HOST --group tailscale
```

SSH 접속 정보는 `/tmp/nixup-json/resolved.json` 또는 `~/.ssh/rnixup/<hostname>.bootstrap.env`에서 자동으로 가져옵니다. 자동 조회에 실패하면 에러로 종료합니다.

---

## 시크릿 자동 주입 동작 (rnixup/rnixstrap)

`rnixup` 배포와 `rnixstrap` 초기 설치 시 시크릿이 **자동으로** 처리됩니다.

### 변경된 파일만 전송 (stale 체크)

서버에 이미 동일한 파일이 있으면 전송을 건너뜁니다:

1. 서버에 단일 SSH 명령으로 현재 파일들의 SHA256 해시를 일괄 조회
2. 로컬 복호화된 파일 해시와 비교
3. 동일하면 `Skip: 변경 없음` 로그 출력 후 건너뜀
4. 다르거나 없으면 `신규` / `갱신` 로그 출력 후 전송

모든 파일이 동일하면 전송 자체를 건너뜁니다:
```
NIXSEC Done      | 변경된 시크릿 없음 — 전송 건너뜀
```

### SSH 실패 시 fallback

해시 조회를 위한 SSH 연결이 실패하면 경고를 출력하고 모든 파일을 전송합니다:
```
NIXSEC Warn      | 서버 해시 확인 실패 — 전체 전송으로 fallback
```

---

## secrets.json 형식

시크릿 매핑 정보는 `hosts/_deploy/<hostname>.secrets/secrets.json`에 저장합니다.

```json
{
  "appId": "1234567",
  "groups": {
    "<group>": {
      "repo": "owner/nix-secrets",
      "installationId": "9876543",
      "secrets": {
        "<레포 내 경로>": "<서버 상대 경로>",
        "headscale/noise_private_key": "var/lib/headscale/noise_private.key"
      }
    }
  }
}
```

`appId`와 `installationId`가 있으면 GitHub Apps JWT 인증을 사용하고, 없으면 `gh api` 폴백을 사용합니다.
