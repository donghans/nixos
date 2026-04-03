# 🚀 NixOS 기반 차세대 경량 하이퍼바이저 서버 구축 계획 (Project: Server-Nix)

본 문서는 Proxmox의 중량급 오버헤드를 제거하고, NixOS의 선언적 관리와 최신 경량 가상화 기술을 결합하여 **저사양에서도 고효율을 내는 개발/PoC용 서버** 구축을 위한 마스터 플랜입니다.

---

## 1. 핵심 비전 (Core Vision)
- **Extreme Efficiency:** Btrfs와 zram을 결합하여 물리 자원 한계 극복.
- **Seamless Connectivity:** Double/Triple NAT 환경에서도 MagicDNS와 FRP를 통해 전 세계 어디서든 즉시 접속.
- **Hybrid Management:** 핵심 시스템은 NixOS로 선언적 관리, 개별 서비스는 Incus 컨테이너/VM으로 유연하게 운영.
- **Snapshot-Centric:** 개발 결과물(Coolify 등)의 즉각적인 복원 지점 생성 및 롤백 지원.

---

## 2. 통합 기술 스택 (Integrated Tech Stack)

### 📂 [Storage] Btrfs (The Foundation)
- **Role:** 고성능 스토리지 엔진 및 스냅샷 관리.
- **Strategy:** 
    - **Reflink & Snapshot:** VM 이미지 복제 시 물리 용량 소모 없는 즉시 복사(Copy-on-Write) 구현.
    - **Compression:** `zstd` 투명 압축을 통해 SSD 수명 연장 및 디스크 공간 극대화.
    - **Subvolumes:** `/var/lib/incus`를 독립 서브볼륨으로 관리하여 호스트와 가상 머신 데이터 분리 및 안전성 확보.

### ⚙️ [Virtualization] Incus (The Engine)
- **Role:** VM(QEMU)과 컨테이너(LXC)를 동시에 지원하는 통합 하이바이저.
- **Strategy:** 
    - **Incus-UI:** 공식 웹 대시보드를 활성화하여 브라우저에서 가상 리소스 관리 및 콘솔 접속 지원.
    - **Diversity:** OpenWrt(VM)부터 Coolify, Vaultwarden(LXC)까지 용도에 맞는 가상화 방식 선택.

### 🌐 [Connectivity] Headscale + Caddy + FRP (The Access)
- **Role:** 복잡한 NAT 환경을 관통하는 지능형 네트워크 인프라.
- **Strategy:** 
    - **Headscale (Tailnet):** MagicDNS를 통해 각 서비스에 `service.server-nix` 같은 고유 도메인 부여.
    - **Caddy:** MagicDNS 도메인에 대한 **Zero-Config SSL(HTTPS)** 자동 발급 및 초간편 리버스 프록시 구축.
    - **FRP (Fast Reverse Proxy):** 고정 IP가 없는 환경에서 외부 VPS를 경유하여 Headscale 제어부 등 핵심 포트 노출.

### ⚡ [Optimization] zram & Cockpit (The Performance)
- **Role:** 시스템 자원 효율 극대화 및 실시간 모니터링.
- **Strategy:** 
    - **zram (zstd):** 물리 램의 50~75%를 압축 스왑으로 할당하여 OOM 방지 및 서비스 수용량 극대화.
    - **Cockpit:** 호스트 서버의 CPU/RAM/Disk 상태를 직관적으로 파악할 수 있는 경량 웹 대시보드.

---

## 3. 구현 단계별 로드맵 (Roadmap)

### Phase 1: 시스템 빌드 및 최적화
- [ ] **Btrfs 기반 NixOS 설치:** 최적화된 서브볼륨 구조(`@`, `@home`, `@incus`) 설계.
- [ ] **zram 활성화:** `zstd` 알고리즘 기반의 압축 스왑 구성으로 가용 메모리 확보.
- [ ] **커널 튜닝:** 하이퍼바이저 최적화(IOMMU 활성화 등) 및 불필요한 기본 서비스 제거.

### Phase 2: 가상화 및 사설망 구축
- [ ] **Incus 엔진 설정:** 스토리지 풀을 Btrfs로 지정하여 즉각적인 스냅샷 및 클론 성능 확보.
- [ ] **Headscale 통합:** 호스트와 가상 머신들을 하나의 Tailnet으로 결합하여 MagicDNS 환경 구축.
- [ ] **네트워킹 브리지:** 각 가상 머신이 독립적인 IP를 가질 수 있도록 가상 브리지 구성.

### Phase 3: 외부 노출 및 관리 자동화
- [ ] **Caddy 프록시 설정:** MagicDNS 도메인 기반의 자동 SSL 및 리버스 프록시 연동.
- [ ] **FRP 터널링:** 외부 VPS와 연동하여 NAT 뒤의 핵심 서비스를 안정적으로 외부 노출.
- [ ] **Cockpit UI:** 시스템 모니터링 및 기본 관리를 위한 웹 대시보드 활성화.

---

## 4. 예상 워크플로우 (Operational Workflow)

1. **서비스 배포:** 신규 서비스 필요 시 `incus launch`로 컨테이너 생성.
2. **테스트 및 배포:** Coolify 등을 활용해 팀원들의 결과물을 즉각적으로 호스트.
3. **복원 지점:** 업데이트나 위험한 변경 전 `incus snapshot create`로 안전장치 마련.
4. **외부 공유:** 사내 직원들이 MagicDNS 주소만으로 내부 서비스에 안전하게 접근.

---

## 5. 기존 하이퍼바이저 대비 경쟁력

| 비교 항목 | Proxmox (ZFS 기반) | Server-Nix (Btrfs + Incus) |
| :--- | :--- | :--- |
| **자원 효율성** | 무거움 (높은 RAM 유휴 점유율) | **극도로 가벼움 (zram/Btrfs 압축)** |
| **네트워크 관리** | 포트 포워딩/VPN 수동 설정 | **MagicDNS를 통한 도메인 자동 할당** |
| **NAT 관통** | 별도 솔루션 필요 (복잡) | **FRP + Headscale 내장 전략** |
| **설정 관리** | GUI 수동 설정 (재현성 낮음) | **NixOS 기반 완전 선언적 관리** |

---

## 6. [Appendix] 특수 환경 및 확장 전략

### 6.1 저사양/에지 장비 최적화 (예: Raspberry Pi 2GB + NVMe)
- **가상화 제한:** 메모리 오버헤드 방지를 위해 VM 기능을 끄고 **LXC 컨테이너** 중심으로 운영.
- **zram 강화:** 물리 램의 50~75% 할당 및 NVMe 기반 보조 스왑 구성으로 안정성 확보.
- **Btrfs 최적화:** `zstd:3` 압축으로 SD/SSD 쓰기 부하 감소 및 입출력 성능 향상.
- **선언적 우선:** 핵심 유틸리티는 호스트(NixOS)에서 직접 구동하여 컨테이너 오버헤드마저 제거.

### 6.2 멀티 노드 분산 운영 (예: Beelink SER7 32GB + 64GB)
- **메인 노드 (32GB):** Coolify Controller, Headscale, Caddy/FRP 등 전체 인프라의 사령탑.
- **서브 노드 (64GB):** 실제 연산 부하(Coolify Worker, 대규모 테스트 컨테이너) 담당.
- **장점:** 장애 격리(Fault Isolation) 및 빌드 부하 분산을 통해 메인 서비스 가용성 극대화.
- **Incus Cluster:** 두 노드를 하나의 풀로 묶어 컨테이너의 실시간 기기 간 이동(Migration) 가능.

### 6.3 클라우드 확장 및 하이브리드 운영 (Terraform)
본 플랜을 기반으로 외부 퍼블릭 클라우드(AWS, GCP 등)를 연동하는 전략입니다.
- **Terraform (The Cloud Bridge):** NixOS만으로 관리가 어려운 외부 클라우드 자원의 선언적 생명주기 관리.
- **Hybrid Networking:** Headscale(Tailnet)을 통해 로컬 서버와 외부 클라우드 인스턴스를 하나의 사설망으로 결합.
- **Global Exit Node:** 전 세계 각 지역의 클라우드 인스턴스를 Exit Node로 설정하여 글로벌 네트워크 테스트 환경 구축.
- **장점:** 로컬 인프라의 자원 한계를 클라우드로 유연하게 확장하고, 모든 자원을 코드로 일관되게 관리.

---

*본 계획서는 향후 서버 구축 및 확장 시 기준 문서로 활용되며, 필요에 따라 수시로 업데이트됩니다.*
