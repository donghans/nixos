# lightsail-nixos-headscale — IAM Roles Anywhere 복구 계획

## 현재 상태 (2026-04-29)

- nixup은 적용됐으나 두 가지 실패:
  1. `step-ca.service`: DB 디렉토리 권한 오류 (`/var/lib/step-ca/db: permission denied`)
     - 원인: 이전 디버깅 세션에서 root로 step-ca 수동 실행 → DB 소유권 오염
     - DynamicUser=true 서비스라 chown 수동 적용이 효과 없음
  2. `acme-order-renew-r.772610158.xyz.service`: lego 플래그 오류
     - 원인: `extraLegoRunFlags = ["--dns.resolvers=1.1.1.1:53"]` → lego 글로벌 플래그를 서브커맨드 위치에 전달
     - 수정 완료 (로컬 코드에서 제거), 아직 커밋/push 안 됨

---

## 할 일 목록

### [ ] 1. 로컬: lego 플래그 제거 커밋 & push
- `mods/sys/services/aws-roles-anywhere.nix`에서 `extraLegoRunFlags` 제거 완료
- `git commit && git push` 실행

### [ ] 2. 서버: step-ca DB 초기화
- `sudo rm -rf /var/lib/step-ca/db`
- CA 키/인증서는 `/var/lib/step-ca-secrets/`에 별도 보관 → 안전
- DB는 step-ca 재시작 시 자동 재생성

### [ ] 3. 서버: git pull && nixup os
- 변경사항: lego 플래그 제거

### [ ] 4. 검증: step-ca 정상 기동
- `systemctl status step-ca`
- `curl -k https://c.772610158.xyz:8443/health`

### [ ] 5. 검증: ACME 인증서 발급
- `systemctl status acme-r.772610158.xyz.service`
- `/var/lib/acme/r.772610158.xyz/cert.pem` 존재 확인

### [ ] 6. 검증: AWS IAM Roles Anywhere
- `aws sts get-caller-identity` → 계정 `732799293614` 반환 확인

### [ ] 7. 검증: SSM Agent
- `systemctl status amazon-ssm-agent`

---

## 핵심 수정 사항 (이번 세션에서 nix config 반영 완료)

| 수정 | 파일 | 이유 |
|------|------|------|
| `services.resolved.extraConfig = "Cache=no-negative"` | `lightsail-nixos-headscale.nix` | resolved가 NXDOMAIN 캐시 → step-ca DNS-01 검증 실패 |
| `dhcpV4Config.UseDNS = false` (ens5) | `lightsail-nixos-headscale.nix` | AWS VPC DNS(172.26.0.2)가 Default Route DNS로 설정되어 1.1.1.1/8.8.8.8 무력화 |
| `extraLegoRunFlags` 제거 | `aws-roles-anywhere.nix` | lego 글로벌 플래그를 서브커맨드 위치에 전달 불가 |

---

## 참고

- 서버 SSH: `ssh -i ~/.ssh/rnixup/lightsail-nixos-headscale.pem ec2-user@3.34.148.209`
- step-ca 시크릿 경로: `/var/lib/step-ca-secrets/intermediate_ca.key`, `/var/lib/step-ca-secrets/password`
- Cloudflare 토큰: `/var/lib/secrets/cloudflare-token`
