# Headscale 마이그레이션: Lightsail $20 → EC2 t4g.micro + Lightsail $5

> **실행 환경**: 이 문서의 모든 명령어는 nixos 레포가 있는 로컬 머신에서 실행.  
> **전제**: `gh auth login` 완료, `~/.ssh/rnixup/` 디렉터리 존재.

---

## 아키텍처

### 현재 (Lightsail $20 단일)

```
인터넷
  └── e.772610158.xyz → Lightsail $20 (x86_64)
        headscale + step-ca + DERP 릴레이
        Roles Anywhere (step-ca PKI) → AWS 자격증명
        월 $20, 4TB 포함 트래픽
```

### 신규 (EC2 + Lightsail $5 분리)

```
인터넷
  └── e2.772610158.xyz → Lightsail $5 (공인 IP, ap-northeast-2)
        ├── Caddy :443 (TLS 종료)
        │     ├── /derp* → localhost:3340 (derper HTTP 모드)
        │     └── * → EC2 사설 IP:8080 (VPC 백본, 무료)
        ├── derper STUN UDP :3478
        ├── tailscale exit node
        └── 월 $5, 1TB 포함 트래픽
          │
          │ VPC Peering (Lightsail VPC ↔ default VPC)
          │
  EC2 t4g.micro (사설 IP only, aarch64, ap-northeast-2)
        headscale 컨트롤 플레인 (0.0.0.0:8080, 외부 노출 없음)
        IAM Instance Profile → AWS 자격증명 (자동, 별도 설정 불필요)
        litestream → S3 (headscale DB 실시간 백업)
        월 ~$8 (인스턴스 $6.1 + EBS $1.6)
        SSH 접근: EIP 임시 부착 (설치/유지보수 시) → 평소엔 Tailscale IP

합계: ~$13/월  (현재 $20 → $7 절감 + Roles Anywhere 복잡도 제거)
```

---

## 사전 준비 (AWS 콘솔 + Cloudflare — 한 번만)

### 1. S3 버킷 생성 (headscale DB 백업용)

```
AWS 콘솔 → S3 → 버킷 생성
  이름: headscale-backup-<임의문자> (전 세계 유일해야 함)
  리전: ap-northeast-2
  버전 관리: 활성화
  퍼블릭 액세스: 모두 차단
```

버킷명 확정 후 `hosts/ec2-nixos-headscale.nix` 상단 `s3BackupBucket` 변수 업데이트:
```nix
s3BackupBucket = "실제-버킷명";
```

### 2. IAM Instance Profile 생성 (EC2용)

```
AWS 콘솔 → IAM → 역할 → 역할 만들기
  신뢰할 수 있는 개체: AWS 서비스 → EC2
  권한 추가:
    - AmazonSSMManagedInstanceCore
    - AmazonS3FullAccess (또는 버킷 한정 인라인 정책)
  역할 이름: ec2-headscale-role
```

인라인 정책으로 S3 버킷만 허용하려면:
```json
{
  "Effect": "Allow",
  "Action": ["s3:GetObject","s3:PutObject","s3:DeleteObject","s3:ListBucket"],
  "Resource": [
    "arn:aws:s3:::실제-버킷명",
    "arn:aws:s3:::실제-버킷명/*"
  ]
}
```

### 3. Lightsail VPC Peering 활성화

```
Lightsail 콘솔 → Account → Advanced → Enable VPC peering (ap-northeast-2)
```

활성화 후 Lightsail 인스턴스에 사설 IP가 생김. 메모: `LIGHTSAIL_PRIVATE_IP=<사설 IPv4>`

### 4. EC2 인스턴스 생성

```
AWS 콘솔 → EC2 → 인스턴스 시작
  AMI: Amazon Linux 2023 (ARM)  ← nix 설치 후 nixstrap으로 NixOS 덮어씀
  인스턴스 유형: t4g.micro
  네트워크: default VPC  ← VPC peering이 default VPC와 연결됨
  퍼블릭 IP 자동 할당: 비활성화  ← 사설 IP만 사용
  키 페어: 새로 생성 → ec2-nixos-headscale → ~/.ssh/rnixup/ec2-nixos-headscale.pem 저장
  IAM 인스턴스 프로파일: ec2-headscale-role (위에서 생성)
  스토리지: gp3 20GB
  보안 그룹:
    - TCP 22  (SSH, EIP 부착 시 내 IP만)
    - TCP 8080 (headscale, Lightsail 사설 IP만)
```

인스턴스 생성 후 사설 IP 메모: `EC2_PRIVATE_IP=<사설 IPv4>`

EIP 생성 및 임시 부착 (rnixstrap 설치용):
```
AWS 콘솔 → EC2 → Elastic IPs → 탄력적 IP 주소 할당 → 인스턴스에 연결
```
`EC2_EIP=<탄력적 IP>`

### 5. Lightsail $5 인스턴스 생성

```
AWS 콘솔 → Lightsail → 인스턴스 생성
  리전: 서울 (ap-northeast-2)
  OS: Amazon Linux 2023  ← NixOS 미사용, 셸 스크립트로 직접 구성
  플랜: $5 (1GB RAM, 1TB 전송)
  인스턴스 이름: lightsail-headscale
```

키 페어: 기존 키 또는 새로 생성 → `~/.ssh/rnixup/lightsail-headscale.pem`

Lightsail 방화벽 설정 (인스턴스 → 네트워킹 탭):
```
TCP 22   — SSH
TCP 80   — ACME Let's Encrypt (Caddy)
TCP 443  — headscale + DERP relay (Caddy TLS 종료)
UDP 3478 — STUN (derper 직접)
UDP 41641 — tailscale WireGuard
```

인스턴스 퍼블릭 IP 메모: `LIGHTSAIL_IP=<퍼블릭 IPv4>`

### 6. Cloudflare DNS 레코드 추가

Cloudflare 대시보드 → 772610158.xyz → DNS 레코드:
```
A  e2.772610158.xyz  →  <LIGHTSAIL_IP>  프록시: OFF (DNS only)
```

모든 외부 트래픽(headscale + DERP)이 Lightsail 단일 IP로 진입. EC2는 공인 IP 없음.

---

## EC2 headscale 설치

> EIP가 부착된 상태에서 진행. 설치 완료 + Tailscale 등록 후 EIP 제거.

### 7. EC2에 nix 설치

```bash
EC2_IP=$EC2_EIP  # 탄력적 IP 사용
ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@$EC2_IP

# 서버에서:
curl -L https://nixos.org/nix/install | sh -s -- --daemon
exit
```

### 8. rnixstrap으로 NixOS 설치

```bash
# 로컬 머신에서:
EC2_IP=$EC2_EIP  # 탄력적 IP 사용

# nixos 레포 sync 후 원격 실행
ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@$EC2_IP \
  "curl -fsSL https://raw.githubusercontent.com/donghans/nixos/stable/nixstrap.sh | bash" 
# 또는 레포 클론 후 로컬 nixstrap.sh 실행 방식으로 진행 (기존 방식과 동일)
```

nixstrap 대화형 프롬프트:
- 호스트명: `ec2-nixos-headscale`
- 디스크: `/dev/nvme0n1`
- 포맷: yes
- 파티션: yes

설치 완료 후 SSH public key가 `hosts/deploy/ec2-nixos-headscale.pub`에 자동 생성됨.

### 9. agenix 시크릿 재암호화

새 서버의 SSH 호스트 키를 시크릿 레포에 추가해야 OIDC secret을 복호화 가능:

```bash
# 새 서버의 SSH 호스트 공개키 확인
ssh-keyscan -t ed25519 $EC2_IP

# nixsec 또는 agenix 워크플로우로 새 키 등록
# (기존 lightsail-nixos-headscale-secrets 레포의 .pubkey 업데이트 후 재암호화)
nixsec  # 기존 방식대로
```

### 10. OIDC 시크릿 배포

```bash
# 기존 Lightsail 서버에서 OIDC 시크릿 확인 후 새 EC2에 배포
ssh -i ~/.ssh/rnixup/lightsail-nixos-headscale.pem ec2-user@<OLD_LIGHTSAIL_IP> \
  "cat /var/lib/nix-secrets/headscale/oidc_client_secret"

# EC2에 배포
ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@$EC2_IP \
  "sudo mkdir -p /var/lib/nix-secrets/headscale && \
   echo '<OIDC_SECRET>' | sudo tee /var/lib/nix-secrets/headscale/oidc_client_secret && \
   sudo chmod 600 /var/lib/nix-secrets/headscale/oidc_client_secret"
```

---

## Lightsail $5 설치 (Amazon Linux 2023, NixOS 미사용)

> nixos-anywhere는 최소 1.5GB RAM 필요 → Lightsail $5 (512MB)에서 불가.  
> Amazon Linux 2023 기본 이미지에 셸 스크립트로 직접 구성.

### 11. headscale에서 preauth key 생성

```bash
# EC2 headscale이 이미 가동 중인 경우:
ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@$EC2_IP \
  "sudo headscale preauthkeys create -u system --expiration 24h"
# 출력된 key 값을 메모 (PREAUTH_KEY=tskey-auth-...)

# 아직 EC2 headscale 설치 전이면 기존 Lightsail headscale에서 생성:
ssh -i ~/.ssh/rnixup/lightsail-nixos-headscale.pem ec2-user@<OLD_LIGHTSAIL_IP> \
  "sudo headscale preauthkeys create -u system --expiration 24h"
```

### 12. 설정 스크립트 업로드 + 실행

```bash
LIGHTSAIL_IP=<LIGHTSAIL_IP>
PEM=~/.ssh/rnixup/lightsail-headscale.pem
PREAUTH_KEY=<위에서_생성한_키>
EC2_PRIVATE_IP=<EC2_프라이빗_IPv4>

# 스크립트 업로드
scp -i $PEM hosts/deploy/lightsail-headscale-setup.sh ec2-user@$LIGHTSAIL_IP:/tmp/

# 서버에서 root로 실행
ssh -i $PEM ec2-user@$LIGHTSAIL_IP \
  "sudo bash /tmp/lightsail-headscale-setup.sh '$PREAUTH_KEY' '$EC2_PRIVATE_IP'"
```

스크립트가 자동으로 처리하는 항목:
- tailscale 설치 + headscale 등록 (exit node 광고)
- IP 포워딩 활성화
- derper 바이너리 다운로드 (tailscale 릴리즈에서 추출), HTTP 모드(--dev)로 실행
- Caddy 설치 + TLS 종료 + 라우팅 설정 (DERP → 로컬, headscale → EC2 private IP)

### 13. Lightsail Caddy에 headscale 프록시 추가

EC2 사설 IP를 확인한 후 Lightsail의 Caddy 설정에 추가:

```
# lightsail-nixos-derp.nix (또는 배포 스크립트)에서 Caddy 설정:
e2.772610158.xyz {
  reverse_proxy http://<EC2_PRIVATE_IP>:8080
}

d.r.772610158.xyz {
  # 기존 DERP 설정
}
```

Lightsail Caddy 설정 반영 후 Lightsail에서 확인:
```bash
curl -s https://e2.772610158.xyz/health  # headscale health endpoint
```

### 14. EIP 제거 (Tailscale 등록 완료 후)

```
AWS 콘솔 → EC2 → Elastic IPs → 인스턴스에서 분리 → 주소 해제
```

이후 EC2 접근은 Tailscale IP로만:
```bash
ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@<TAILSCALE_IP>
```

### 15. headscale에서 exit node 경로 승인

```bash
ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@$EC2_IP \
  "sudo headscale routes list"
# lightsail-headscale의 exit-route ID 확인 후:
ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@$EC2_IP \
  "sudo headscale routes enable -r <ROUTE_ID>"
```

---

## 헤드스케일 마이그레이션

### 16. headscale DB를 기존 서버에서 복사

```bash
# 기존 headscale DB 백업
ssh -i ~/.ssh/rnixup/lightsail-nixos-headscale.pem ec2-user@<OLD_LIGHTSAIL_IP> \
  "sudo sqlite3 /var/lib/headscale/db.sqlite '.backup /tmp/headscale-backup.sqlite'"

# 로컬로 복사
scp -i ~/.ssh/rnixup/lightsail-nixos-headscale.pem \
  ec2-user@<OLD_LIGHTSAIL_IP>:/tmp/headscale-backup.sqlite \
  /tmp/headscale-backup.sqlite

# EC2로 업로드
scp -i ~/.ssh/rnixup/ec2-nixos-headscale.pem \
  /tmp/headscale-backup.sqlite \
  ec2-user@$EC2_IP:/tmp/headscale-backup.sqlite

# EC2에서 복원
ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@$EC2_IP \
  "sudo cp /tmp/headscale-backup.sqlite /var/lib/headscale/db.sqlite && \
   sudo chown headscale:headscale /var/lib/headscale/db.sqlite && \
   sudo systemctl restart headscale"
```

### 17. EC2에서 headscale 동작 확인

```bash
ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@$EC2_IP
  sudo headscale nodes list  # 기존 노드 목록 확인
  sudo systemctl status headscale litestream
```

### 18. Cloudflare DNS 전파 확인

단계 6에서 추가한 레코드가 전파됐는지 확인:
```bash
dig e2.772610158.xyz +short    # Lightsail IP 반환 확인
```

### 19. preauth 라이브러리 업데이트

`core/scripts/nixstrap.lib-preauth.sh`에서 headscale 위치 참조 파일을 변경:

```bash
# 현재: hosts/lightsail-nixos-headscale.toml을 하드코딩
# 변경: hosts/ec2-nixos-headscale.toml 참조
sed -i 's|lightsail-nixos-headscale.toml|ec2-nixos-headscale.toml|g' \
  core/scripts/nixstrap.lib-preauth.sh
```

변경 후 커밋:
```bash
git add core/scripts/nixstrap.lib-preauth.sh
git commit -m "chore: preauth lib headscale 참조를 ec2-nixos-headscale로 전환"
git push
```

---

## 검증

### 20. 전체 동작 확인

```bash
# headscale 노드 목록 (EC2에서)
ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@$EC2_IP \
  "sudo headscale nodes list"

# litestream S3 백업 확인
ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@$EC2_IP \
  "aws s3 ls s3://실제-버킷명/headscale/db/ --region ap-northeast-2"

# DERP 릴레이 확인 (클라이언트에서)
tailscale debug derp --node 900a

# exit node 확인
tailscale exit-node list  # lightsail-headscale 표시 확인

# SSM 확인
aws ssm describe-instance-information --region ap-northeast-2
```

---

## 기존 Lightsail $20 정리 (검증 완료 후)

### 21. 기존 서버 종료

```bash
# 1주일 이상 신규 구성 안정 확인 후 진행
# AWS 콘솔 → Lightsail → lightsail-nixos-headscale 인스턴스 → 삭제
```

### 22. 불필요한 리소스 정리

- Roles Anywhere Trust Anchor (AWS 콘솔 → IAM Roles Anywhere)
- Roles Anywhere Profile / Role
- step-ca 관련 IAM Role (`StepCaRolesAnywhereRole`)
- Cloudflare token (Lightsail용, 새 구성에선 불필요)

---

## 주의사항

- **derper 바이너리**: `lightsail-headscale-setup.sh`이 tailscale 릴리즈 tarball에서 자동 추출.  
  릴리즈에 포함되지 않은 버전이면 스크립트가 명시적으로 오류를 출력하고 대안을 안내함.

- **TLS 인증서**: Caddy가 `e2.772610158.xyz`에 대한 Let's Encrypt 인증서를 자동 발급·갱신.  
  Cloudflare DNS가 Lightsail IP를 가리켜야 ACME 발급 성공.  
  DNS 전파 전이면 caddy 서비스가 인증서 발급 실패로 시작 안 됨.

- **derper HTTP 모드**: derper는 `--dev` 플래그로 HTTP localhost:3340에서 동작 (TLS 없음).  
  외부 TLS는 Caddy가 전담, derper는 STUN UDP:3478만 직접 외부 노출.

- **headscale noise key**: 기존 DB를 복사하면 noise private key도 기존 것 사용.  
  새 서버에서 `/var/lib/headscale/noise_private.key`가 없으면 headscale이 새로 생성  
  → 기존 클라이언트들이 재인증 필요. DB 복사 후 기존 noise key도 함께 복사 권장.

  ```bash
  # noise key도 함께 이전
  ssh ec2-user@<OLD_LIGHTSAIL_IP> "sudo cat /var/lib/headscale/noise_private.key" | \
    ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@$EC2_IP \
      "sudo tee /var/lib/headscale/noise_private.key"
  ```

- **S3 버킷명 업데이트**: `hosts/ec2-nixos-headscale.nix` 상단 `s3BackupBucket` 변수를  
  실제 버킷명으로 변경 후 커밋해야 litestream이 정상 동작.
