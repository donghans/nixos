{pkgs, ...}: let
  mkLxcBackup = instance:
    pkgs.writeShellScript "lxc-backup-${instance}" ''
      set -euo pipefail
      INSTANCE="${instance}"
      SNAP_PREFIX="daily-"
      SNAP_LOCAL_KEEP=7
      SNAP_NAME="$SNAP_PREFIX$(date +%Y-%m-%d)"
      SNAP_PATH="/var/lib/incus/storage-pools/default/containers-snapshots/$INSTANCE"
      SSH_KEY="/var/lib/nix-secrets/backup/ssh-key"
      RESTIC_REPO="sftp:bitstep@mac-studio:/Users/bitstep/backups/${instance}"

      if ! ${pkgs.incus}/bin/incus info "$INSTANCE" &>/dev/null; then
        echo "lxc-backup: $INSTANCE 없음, 건너뜀"
        exit 0
      fi

      # 로컬 btrfs 스냅샷 (빠른 복구용, 7일 롤링)
      if ! ${pkgs.incus}/bin/incus snapshot list "$INSTANCE" --format csv \
          | cut -d, -f1 | grep -qx "$SNAP_NAME"; then
        echo "lxc-backup: 스냅샷 생성 → $SNAP_NAME"
        ${pkgs.incus}/bin/incus snapshot create "$INSTANCE" "$SNAP_NAME"
      fi
      SNAPS=$(${pkgs.incus}/bin/incus snapshot list "$INSTANCE" --format csv \
        | cut -d, -f1 | grep "^$SNAP_PREFIX" | sort)
      COUNT=$(echo "$SNAPS" | grep -c . || true)
      if [ "$COUNT" -gt "$SNAP_LOCAL_KEEP" ]; then
        echo "$SNAPS" | head -n $(( COUNT - SNAP_LOCAL_KEEP )) | while read -r snap; do
          echo "lxc-backup: 로컬 스냅샷 삭제 → $snap"
          ${pkgs.incus}/bin/incus snapshot delete "$INSTANCE" "$snap"
        done
      fi

      # restic: btrfs 스냅샷을 mac-studio로 백업
      export RESTIC_REPOSITORY="$RESTIC_REPO"
      export RESTIC_PASSWORD_FILE="/var/lib/nix-secrets/backup/restic-password"
      SSH_ARGS="-i $SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"

      restic() {
        ${pkgs.restic}/bin/restic \
          -o "sftp.args=$SSH_ARGS" \
          "$@"
      }

      restic snapshots &>/dev/null || restic init

      echo "lxc-backup: mac-studio로 백업 중 ($INSTANCE)..."
      restic backup "$SNAP_PATH/$SNAP_NAME"

      # 30일 초과 원격 백업 정리
      restic forget --keep-daily 30 --prune --quiet

      echo "lxc-backup: 완료 ($INSTANCE)"
    '';

  mkService = instance: {
    name = "lxc-backup-${instance}";
    value = {
      description = "${instance} LXC incremental backup to mac-studio";
      after = ["incus-startup.service" "network-online.target"];
      wants = ["network-online.target"];
      path = [pkgs.incus pkgs.restic pkgs.openssh pkgs.coreutils pkgs.gnugrep];
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${mkLxcBackup instance}";
      };
    };
  };

  mkTimer = instance: {
    name = "lxc-backup-${instance}";
    value = {
      description = "${instance} LXC backup timer";
      wantedBy = ["timers.target"];
      timerConfig = {
        OnCalendar = "daily";
        Persistent = true;
        RandomizedDelaySec = "30min";
      };
    };
  };

  instances = ["cardgame" "adx" "class24"];
in {
  systemd.services = builtins.listToAttrs (map mkService instances);
  systemd.timers = builtins.listToAttrs (map mkTimer instances);
}
