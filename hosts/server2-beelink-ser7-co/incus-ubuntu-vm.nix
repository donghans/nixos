{
  pkgs,
  lib,
  ...
}: let
  backupScript = pkgs.writeShellScript "ubuntu-2404-backup" ''
    set -euo pipefail
    INSTANCE="ubuntu-2404"
    SNAP_PREFIX="daily-"
    SNAP_LOCAL_KEEP=7
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
        -d root,size=64GiB \
        -d eth0,type=nic,nictype=bridged,parent=br-lan,mtu=1400
    '';
  };

  # VM 생성 후 openssh 설치 (incus exec 방식 — cloud-init 불필요)
  # tailscale은 ubuntu-2404-proxy LXC가 대신 담당
  systemd.services.incus-setup-ubuntu-vm = {
    description = "Setup openssh in Ubuntu 24.04 VM";
    after = ["incus-update-vm-nic-ubuntu-2404.service"];
    requires = ["incus-update-vm-nic-ubuntu-2404.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "300";
    };
    script = ''
      # sshd가 이미 설치돼 있으면 건너뜀
      if incus exec ubuntu-2404 -- which sshd &>/dev/null; then
        exit 0
      fi

      # VM agent가 응답할 때까지 대기 (NIC 교체 후 재부팅 시간 포함)
      for i in $(seq 1 36); do
        incus exec ubuntu-2404 -- true 2>/dev/null && break
        sleep 5
      done

      if ! incus exec ubuntu-2404 -- true 2>/dev/null; then
        echo "ubuntu-2404: agent 미응답 — setup 건너뜀" >&2
        exit 1
      fi

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
