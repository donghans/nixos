# 현재 상태 (2026-06-07)

## 완료된 것

- EC2 headscale 배포 완료 (43.201.166.32)
- Lightsail headscale-proxy 인스턴스 생성됨 (43.201.236.170)
  - tailscale: lightsail-headscale-proxy, 100.64.0.15
  - 방화벽: 22, 80, 443(TCP), 3478(UDP), 8000-8999(TCP), 41641(UDP)
- DNS `e.772610158.xyz` → `43.201.236.170` 변경됨
- server2-beelink-ser7-co tailscale 연결됨 (100.64.0.2)
  - exit node + 192.168.11.0/24 route 승인됨
  - headscale node ID: 4

## 지금 진행 중

- **Caddy TLS 인증서 발급 중** — `curl -s https://e.772610158.xyz/health`가 아직 실패
  - 포트는 열렸고 Caddy는 active, 인증서 발급에 수 분 소요
  - 완료되면 headscale 전체 복구됨

## 집에서 확인할 것

1. headscale 접속 확인:
   ```bash
   curl -s https://e.772610158.xyz/health
   # → {"status":"pass"} 나오면 OK
   ```

2. tailscale netcheck (exit node 끈 상태):
   ```bash
   tailscale netcheck
   # UDP: true, Nearest DERP: Korea (EC2) 나와야 함
   ```

3. 나머지 노드 재등록 필요:
   - beelink-ser7-co (현재 headscale 노드 ID 1, user 없음)
   - mac-studio, 기타 노드들

## 알려진 버그/미완성

### ts-keygen.sh 2 bytes 문제
- NixOS tailscaled가 `--state` 옵션을 무시하고 `/var/lib/tailscale`을 씀
- 생성된 state 파일이 항상 2 bytes (빈 파일) → nixsec에 올려도 쓸모없음
- **임시 해결**: 노드마다 직접 `tailscale up` → URL → `headscale nodes register` 방식
- 근본 해결 필요

### lightsail-proxy-sync.sh DNAT 빈 IP 문제
- 갱신 모드에서 DNAT 현재 IP가 없을 때 `to::3478`(빈 IP)으로 설정됨
- 수동으로 수정했지만 코드 수정 필요
- `_ls_update_dnat`의 OLD_IP 빈 값 처리 개선 필요

### 기존 lightsail-headscale 인스턴스 (52.79.193.53)
- 아직 삭제 안 됨, 마이그레이션 완료 후 사용자가 직접 삭제 예정

### headscale 노드 정리 필요
- ID 1: beelink-ser7-co (user 없음, offline) — tailscale 재등록 시 정리
- invalid-* 노드들 — OIDC 재등록 후 정리

## IAM 정책 현재 상태

EC2 Instance Profile에 `lightsail:*` 추가됨 (2026-06-07)
- 이전: 일부 액션만 있었음
- 권고: 나중에 필요한 액션만 남기도록 축소
