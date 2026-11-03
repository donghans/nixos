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
      # 2026-10-24 세 서비스가 mac-studio 와의 연결이 끊긴 채 10일간 멈췄다(ssh 소켓이 마지막 송수신 후
      # 방치, 유지 신호·타임아웃이 없어 영원히 대기). ServerAlive 로 응답 없는 연결은 약 2분(30초×4)
      # 안에 끊고, ConnectTimeout 으로 접속 대기를 제한한다.
      SSH_ARGS="-i $SSH_KEY -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=30 -o ServerAliveCountMax=4 -o ConnectTimeout=30"
      # systemd 서비스 환경에는 HOME·XDG_CACHE_HOME 이 없어 restic 이 캐시를 못 쓴다(경고 + 느림).
      # incus-ubuntu-vm.nix 의 게스트 백업과 같은 방식으로 지정한다.
      export XDG_CACHE_HOME=/var/cache

      restic() {
        ${pkgs.restic}/bin/restic \
          -o "sftp.args=$SSH_ARGS" \
          "$@"
      }

      restic snapshots &>/dev/null || restic init
      # 이전 실행이 비정상 종료하며 남긴 오래된 잠금을 지운다(기본 동작은 stale 잠금만 제거; --remove-all 금지).
      # 2026-07-03 의 잠금이 남아 `forget --prune`(배타 잠금)이 그 뒤로 계속 실패해, 30일 보관 정책인데
      # 저장소마다 스냅샷이 123개 쌓였다(2026-11-03 실측). incus-ubuntu-vm.nix 의 게스트 백업(6b597e9)과 같은 처방.
      restic unlock

      echo "lxc-backup: mac-studio로 백업 중 ($INSTANCE)..."
      restic backup "$SNAP_PATH/$SNAP_NAME"

      # 30일 초과 원격 백업 정리.
      # --group-by host 가 필수다: restic 은 기본으로 (호스트, 백업 경로) 별로 묶어 보관 정책을 적용하는데,
      # 이 스크립트는 매일 경로가 바뀌어(.../daily-YYYY-MM-DD) 스냅샷마다 그룹이 달라진다. 그러면 모든 그룹이
      # 1개라 --keep-daily 30 이 전부 보관해, 2026-06 부터 정리가 한 번도 안 됐다(2026-11-03 실측: 저장소마다
      # 124개, dry-run 에서 `keep 1 snapshots`; --group-by host 로는 94개가 정리 대상).
      # 저장소가 인스턴스 하나 전용이므로 host 로만 묶어도 섞이지 않는다.
      restic forget --group-by host --keep-daily 30 --prune --quiet

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
        # oneshot 의 기본 시작 제한은 무제한이라 한 번 멈추면 영원히 `activating` 이다(10일간 그랬다).
        # LXC 가 작아 평소엔 몇 분이면 끝난다. 정지 시 systemd 가 cgroup 전체를 정리하고 다음 날 다시 시도한다.
        TimeoutStartSec = "6h";
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
