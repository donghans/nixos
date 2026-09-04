{
  pkgs,
  lib,
  ...
}: let
  backupScript = pkgs.writeShellScript "ubuntu-2404-backup" ''
    set -euo pipefail
    INSTANCE="ubuntu-2404"
    SNAP_PREFIX="daily-"
    # 2026-09-04: 7→1 — 로컬 스냅샷은 오늘치 1개만 둔다(빠른 롤백용). 이력은 로컬에 쌓지 않고
    # mac-studio restic 저장소(30일 보관, 아래)가 전담한다. 원인: btrfs 쿼터(256GiB)가 매일
    # 스냅샷 7개 누적으로 꽉 차 ubuntu-2404 VM 파일시스템이 I/O 에러로 죽는 사고가 있었다 —
    # 로컬 스냅샷이 원본과 같은 쿼터를 그대로 물려받아 실사용량을 배로 불렸다.
    SNAP_LOCAL_KEEP=1
    SNAP_NAME="$SNAP_PREFIX$(date +%Y-%m-%d)"
    SNAP_PATH="/var/lib/incus/storage-pools/default/virtual-machines-snapshots/$INSTANCE"
    SSH_KEY="/var/lib/nix-secrets/backup/ssh-key"
    RESTIC_REPO="sftp:bitstep@mac-studio:/Users/bitstep/backups/ubuntu-2404"

    if ! ${pkgs.incus}/bin/incus info "$INSTANCE" &>/dev/null; then
      echo "ubuntu-2404-backup: $INSTANCE 없음, 건너뜀"
      exit 0
    fi

    # 로컬 btrfs 스냅샷 (빠른 복구용, 7일 롤링)
    if ! ${pkgs.incus}/bin/incus snapshot list "$INSTANCE" --format csv \
        | cut -d, -f1 | grep -qx "$SNAP_NAME"; then
      echo "ubuntu-2404-backup: 스냅샷 생성 → $SNAP_NAME"
      ${pkgs.incus}/bin/incus snapshot create "$INSTANCE" "$SNAP_NAME"
    fi
    SNAPS=$(${pkgs.incus}/bin/incus snapshot list "$INSTANCE" --format csv \
      | cut -d, -f1 | grep "^$SNAP_PREFIX" | sort)
    COUNT=$(echo "$SNAPS" | grep -c . || true)
    if [ "$COUNT" -gt "$SNAP_LOCAL_KEEP" ]; then
      echo "$SNAPS" | head -n $(( COUNT - SNAP_LOCAL_KEEP )) | while read -r snap; do
        echo "ubuntu-2404-backup: 로컬 스냅샷 삭제 → $snap"
        ${pkgs.incus}/bin/incus snapshot delete "$INSTANCE" "$snap"
      done
    fi

    # restic: 오늘 스냅샷의 btrfs 서브볼륨을 직접 백업 (VM 실행 중에도 일관성 보장)
    export RESTIC_REPOSITORY="$RESTIC_REPO"
    export RESTIC_PASSWORD_FILE="/var/lib/nix-secrets/backup/restic-password"
    SSH_ARGS="-i $SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

    restic() {
      ${pkgs.restic}/bin/restic \
        -o "sftp.args=$SSH_ARGS" \
        "$@"
    }

    restic snapshots &>/dev/null || restic init

    echo "ubuntu-2404-backup: mac-studio로 백업 중..."
    restic backup "$SNAP_PATH/$SNAP_NAME"

    # 30일 초과 원격 백업 정리
    restic forget --keep-daily 30 --prune --quiet

    echo "ubuntu-2404-backup: 완료"
  '';
  mkTailscaleProxy = import ../_lib/incus-tailscale-proxy.nix {inherit lib pkgs;};
in {
  imports = [
    (mkTailscaleProxy "ubuntu-2404" {
      vmName = "ubuntu-2404";
      internalBridge = "incusbr-dev";
      lxcIp = "10.0.1.1";
      vmIp = "10.0.1.2";
      internalSubnet = "10.0.1.0/24";
      stateFile = "/var/lib/nix-secrets/tailscale/system/ubuntu-2404.state";
    })
  ];

  # ubuntu:24.04는 cloud-init 미포함 미니멀 이미지 → incus exec으로 직접 설치
  systemd.services.incus-create-ubuntu-vm = {
    description = "Create Ubuntu 24.04 Incus VM if not exists";
    after = ["incus-startup.service" "systemd-networkd.service"];
    requires = ["incus-startup.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gawk];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      if incus info ubuntu-2404 &>/dev/null; then
        CONFIG=$(incus config show ubuntu-2404 --expanded 2>/dev/null)
        # br-lan이든 internal bridge든 이미 설정된 경우 종료
        if echo "$CONFIG" | grep -q 'parent: br-lan' \
            || echo "$CONFIG" | grep -qE 'parent: incusbr-'; then
          exit 0
        fi
        # NIC를 br-lan으로 교체
        STATUS=$(incus info ubuntu-2404 2>/dev/null | awk '/^Status:/{print $2}')
        [ "$STATUS" = "RUNNING" ] && incus stop ubuntu-2404 --force
        incus config device remove ubuntu-2404 eth0 2>/dev/null || true
        incus config device add ubuntu-2404 eth0 nic nictype=bridged parent=br-lan mtu=1400
        [ "$STATUS" = "RUNNING" ] && incus start ubuntu-2404
        exit 0
      fi

      # ubuntu remote 없으면 등록
      if ! incus remote list --format=csv | cut -d, -f1 | grep -qx "ubuntu"; then
        incus remote add ubuntu https://cloud-images.ubuntu.com/releases \
          --protocol=simplestreams --public
      fi

      incus launch ubuntu:24.04 ubuntu-2404 --vm \
        -c limits.cpu=4 \
        -c limits.memory=16GiB \
        -d root,size=256GiB \
        -d eth0,type=nic,nictype=bridged,parent=br-lan,mtu=1400
    '';
  };

  # VM 생성 후 openssh 설치 (incus exec 방식 — cloud-init 불필요)
  # tailscale은 ubuntu-2404-proxy LXC가 대신 담당
  systemd.services.incus-setup-ubuntu-vm = {
    description = "Setup openssh in Ubuntu 24.04 VM";
    after = ["incus-update-vm-nic-ubuntu-2404.service"];
    requires = ["incus-update-vm-nic-ubuntu-2404.service"];
    # incus-create-ubuntu-vm 재시작 시(VM 재생성) 함께 재실행
    partOf = ["incus-create-ubuntu-vm.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "300";
    };
    script = ''
      # sshd 설치는 최초 1회만 (이후는 건너뜀). 도커 설치/정리 타이머는 아래에서
      # 별도로 idempotent 체크하므로, sshd가 이미 있다고 전체를 건너뛰지 않는다 —
      # 안 그러면 이미 프로비저닝된 VM엔 새로 추가한 도커 선언이 영영 반영되지 않는다.
      if ! incus exec ubuntu-2404 -- which sshd &>/dev/null; then
        # VM agent가 응답할 때까지 대기 (NIC 교체 후 재부팅 시간 포함)
        for i in $(seq 1 36); do
          incus exec ubuntu-2404 -- true 2>/dev/null && break
          sleep 5
        done

        if ! incus exec ubuntu-2404 -- true 2>/dev/null; then
          echo "ubuntu-2404: agent 미응답 — setup 건너뜀" >&2
          exit 1
        fi

        # hostname 설정 (이미지 빌드 시스템 임시값 덮어쓰기)
        incus exec ubuntu-2404 -- hostnamectl set-hostname ubuntu-2404
        incus exec ubuntu-2404 -- bash -c "
          sed -i 's/distrobuilder-[^ ]*/ubuntu-2404/g' /etc/hosts
          echo ubuntu-2404 > /etc/hostname
        "

        # PermitEmptyPasswords yes: LXC proxy가 인증 레이어이므로 VM 패스워드 불필요
        incus exec ubuntu-2404 -- apt-get update -qq
        incus exec ubuntu-2404 -- apt-get install -y openssh-server
        incus exec ubuntu-2404 -- bash -c "
          sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
          sed -i 's/^#\?PermitEmptyPasswords.*/PermitEmptyPasswords yes/' /etc/ssh/sshd_config
          passwd -d ubuntu
          systemctl enable --now ssh
          systemctl reload ssh
        "
      fi

      # VM agent가 응답 안 하면(예: 방금 위 블록을 건너뛰고 VM이 꺼져있는 등) 이후 단계도 의미 없음
      if ! incus exec ubuntu-2404 -- true 2>/dev/null; then
        echo "ubuntu-2404: agent 미응답 — 도커 설치/정리 건너뜀" >&2
        exit 0
      fi

      # 도커 설치 — 이 VM에서 여러 프로젝트를 docker compose로 굴리는 용도로
      # 실사용 중이나(대표님 워크로드), 지금까지 선언 안 된 수동 설치였다. 2026-09-04:
      # 재현성을 위해 선언하되, 이미 설치돼 있으면 apt가 그냥 스킵하므로(idempotent)
      # 이미 떠 있는 이 VM의 도커/컨테이너/이미지에는 영향이 없다 — VM이 새로 만들어질
      # 때만 실제로 새로 설치된다. 공식 저장소(get.docker.com 방식) 사용.
      if ! incus exec ubuntu-2404 -- which docker &>/dev/null; then
        incus exec ubuntu-2404 -- bash -c "
          install -m 0755 -d /etc/apt/keyrings
          curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
          chmod a+r /etc/apt/keyrings/docker.asc
          echo \"deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \$(. /etc/os-release && echo \"\$VERSION_CODENAME\") stable\" \
            > /etc/apt/sources.list.d/docker.list
          apt-get update -qq
          apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
          systemctl enable --now docker
        "
      fi

      # 도커 이미지/빌드캐시 자동 정리 — ~/nixos mods/sys/services/docker.nix의 정책과 동일
      # (48h 지난 이미지 정리 + 빌드캐시 20GB 상한). 2026-09-04: 이 VM 하나에 11개 프로젝트가
      # 같이 돌면서 아무도 정리를 안 해 이미지 178GB(147GB 회수가능) · 빌드캐시 153GB(100%
      # 회수가능)까지 쌓여 btrfs 쿼터를 꽉 채운 사고 재발 방지. (도커 설치 자체는 바로 위
      # 블록에서 선언됨 — 2026-09-04부로 더 이상 별도 부채 아님.)
      incus exec ubuntu-2404 -- bash -c \"cat > /etc/systemd/system/docker-prune.service\" <<'UNIT'
[Unit]
Description=Prune unused Docker images and build cache
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/docker image prune -af --filter until=48h
ExecStart=/usr/bin/docker builder prune -af --keep-storage=20GB
UNIT
      incus exec ubuntu-2404 -- bash -c \"cat > /etc/systemd/system/docker-prune.timer\" <<'UNIT'
[Unit]
Description=Daily Docker image/build-cache cleanup

[Timer]
OnCalendar=daily
Persistent=true
RandomizedDelaySec=30min

[Install]
WantedBy=timers.target
UNIT
      incus exec ubuntu-2404 -- systemctl daemon-reload
      incus exec ubuntu-2404 -- systemctl enable --now docker-prune.timer
    '';
  };

  systemd.services.ubuntu-2404-backup = {
    description = "ubuntu-2404 incremental backup to mac-studio";
    after = ["incus-startup.service" "network-online.target"];
    wants = ["network-online.target"];
    path = [pkgs.incus pkgs.restic pkgs.openssh pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      ExecStart = "${backupScript}";
    };
  };

  systemd.timers.ubuntu-2404-backup = {
    description = "ubuntu-2404 backup timer";
    wantedBy = ["timers.target"];
    timerConfig = {
      OnCalendar = "daily";
      Persistent = true;
      RandomizedDelaySec = "30min";
    };
  };
}
