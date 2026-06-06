# TODO: headscale DB 초기화 복구 작업

> headscale DB 유실 (2026-06-05, ENI 작업 중 인스턴스 재설치)
> S3 versioning 활성화 완료 / litestream restore 스텝 추가 완료

---

## 지금 바로 (원격)

- [ ] `rnixup ec2-nixos-headscale` — litestream restore 스텝 배포

---

## 현장 전 준비 (원격)

- [ ] headscale 유저 생성
  ```bash
  headscale users create system
  ```

- [ ] preauthkey 발급 (각각 별도 발급)
  ```bash
  headscale preauthkeys create --user system --reusable=false --expiration 24h
  # exitscale  → server2-beelink-ser7-co (exit node)
  headscale preauthkeys create --user system --reusable=false --expiration 24h
  # devserver  → devserver-proxy LXC (incus ubuntu-2404 앞단)
  headscale preauthkeys create --user system --reusable=false --expiration 24h
  # mac-studio → mac studio
  ```

- [ ] 발급된 preauthkey를 시크릿으로 주입
  - `server2-beelink-ser7-co`: `tailscale/system/exitscale.preauth-key`
  - `devserver-proxy`: `tailscale/system/devserver.preauth-key`

---

## 현장 작업 (회사)

- [ ] **beelink-ser7-co** tailscale 재등록
  ```bash
  tailscale login --login-server https://e.772610158.xyz
  # OIDC 브라우저 인증
  ```

- [ ] **server2-beelink-ser7-co** tailscale 재등록
  - preauthkey 시크릿 주입 후 `rnixup server2-beelink-ser7-co`
  - exit node + route advertise (`192.168.11.0/24`) 확인
  - headscale에서 exit node 승인
    ```bash
    headscale routes list
    headscale routes enable -r <route-id>
    ```

- [ ] **devserver-proxy LXC** tailscale 재등록
  - server2 nixup 시 자동 처리됨 (incus-tailscale-proxy-lib)
  - 연결 확인: `headscale nodes list` 에서 ubuntu-2404 확인

- [ ] **mac-studio** tailscale 재등록
  ```bash
  tailscale up --login-server https://e.772610158.xyz --authkey <key>
  ```

---

## 재등록 후 필수 확인

- [ ] **ENI 포워딩 IP 확인** ← 중요
  ```bash
  headscale nodes list
  ```
  `eni-forwarding.nix` 하드코딩 IP와 대조:
  - mac-studio → `100.64.0.5`
  - ubuntu-2404 → `100.64.0.12`

  IP 다르면 `eni-forwarding.nix` 수정 + `rnixup ec2-nixos-headscale`

---

## 보류

- [ ] stirling-pdf NixOS 이전 (proxmox 레거시) + preauthkey 발급
