# ENI 포워딩 활성화 (Mac Studio / Incus VM 전용 공인 IP)

ec2-nixos-headscale에 ENI를 붙여 Mac Studio와 Incus VM에 각각 전용 공인 IP를 부여하는 절차.

## 배경

- EC2 t4g.micro에 ENI 1개 추가 → primary IP + secondary IP로 EIP 2개 확보
- EIP-1 (primary) → Mac Studio Tailscale IP로 DNAT
- EIP-2 (secondary) → Incus VM Tailscale IP로 DNAT
- 설정은 IP 값이 null이면 자동 비활성화 (ENI 없는 상태와 동일)

---

## 순서

### 1. AWS 콘솔 — ENI attach

```
EC2 콘솔 → Network Interfaces → 기존 ENI 선택
→ Actions → Attach → ec2-nixos-headscale 선택 → Device index: 1
```

EC2 인스턴스의 **Source/Destination Check 비활성화** 확인:
```
EC2 인스턴스 선택 → Actions → Networking → Change source/destination check → Stop
```

### 2. eth1 IP 확인

```bash
ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@43.201.166.32 \
  "ip addr show eth1"
```

- `eth1PrimaryIp` = DHCP로 받은 주 IP
- `eth1SecondaryIp` = 수동 추가한 보조 IP
- `eth1Gateway` = 서브넷 게이트웨이 (172.31.48.0/20이면 `172.31.48.1`)

### 3. Tailscale IP 확인

```bash
ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@43.201.166.32 \
  "sudo headscale nodes list"
```

Mac Studio와 Incus VM의 현재 Tailscale IP 메모.

### 4. `eni-forwarding.nix` 값 채우기

파일: `hosts/ec2-nixos-headscale/eni-forwarding.nix`

```nix
eth1PrimaryIp   = "172.31.x.x";   # 2번에서 확인한 primary IP
eth1SecondaryIp = "172.31.x.x";   # 2번에서 확인한 secondary IP
eth1Gateway     = "172.31.48.1";  # 서브넷 게이트웨이
subnetPrefix    = 20;

macStudioTs     = "100.64.x.x";   # 3번에서 확인한 Mac Studio Tailscale IP
incusVmTs       = "100.64.x.x";   # 3번에서 확인한 Incus VM Tailscale IP
```

`hasEni` 체크는 null 비교로 되어 있음:
```nix
hasEni = eth1PrimaryIp != null && eth1SecondaryIp != null && eth1Gateway != null;
```

### 5. 커밋 → 배포

```bash
git add hosts/ec2-nixos-headscale/eni-forwarding.nix
git commit -m "feat: ENI 포워딩 활성화"
git push
rnixup
```

### 6. 검증

```bash
ssh -i ~/.ssh/rnixup/ec2-nixos-headscale.pem ec2-user@43.201.166.32 bash << 'EOF'
ip addr show eth1          # secondary IP 포함 2개 존재
ip rule show               # priority 100/101 policy rule
ip route show table 101    # default via 게이트웨이
nft list ruleset | grep -A5 eni-forwarding
EOF
```

---

## 현재 ENI 정보

- ENI: ec2-nixos-headscale에 이전에 생성된 ENI 사용 (재생성 불필요)
- EIP-1: Mac Studio용 (eth1 primary에 연결)
- EIP-2: Incus VM용 (eth1 secondary에 연결)
- 서브넷: 172.31.48.0/20 → 게이트웨이 172.31.48.1

## 주의

- Tailscale이 EC2에서 먼저 `tailscale up` 으로 등록되어 있어야 DNAT 동작
- ENI detach 시 자동으로 비활성화됨 (hasEni=false → 규칙 없음)
