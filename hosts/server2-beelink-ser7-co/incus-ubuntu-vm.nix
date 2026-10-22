{
  pkgs,
  lib,
  ...
}: let
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
            incus exec ubuntu-2404 -- bash -c "cat > /etc/systemd/system/docker-prune.service" <<'UNIT'
      [Unit]
      Description=Prune unused Docker images and build cache
      After=docker.service
      Requires=docker.service

      [Service]
      Type=oneshot
      ExecStart=/usr/bin/docker image prune -af --filter until=48h
      ExecStart=/usr/bin/docker builder prune -af --keep-storage=20GB
      UNIT
            incus exec ubuntu-2404 -- bash -c "cat > /etc/systemd/system/docker-prune.timer" <<'UNIT'
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

            # 게스트 fstrim 매일 실행 — 2026-10-21: 기본 fstrim.timer(주 1회)로는 게스트가 지운
            # 블록이 호스트 root.img에 계속 남아 btrfs 쿼터(root 크기와 동일)를 채우고, 게스트
            # ext4가 EDQUOT→I/O 에러로 read-only가 되어 ssh까지 죽는 사고가 반복됐다.
            # (스냅샷/restic 백업은 같은 날 제거 — 스냅샷이 쿼터를 이중으로 물려받아 사고를 키웠고,
            # 이 VM은 스냅샷 보관이 중요하지 않다고 판단했다.)
            incus exec ubuntu-2404 -- mkdir -p /etc/systemd/system/fstrim.timer.d
            incus exec ubuntu-2404 -- bash -c "cat > /etc/systemd/system/fstrim.timer.d/daily.conf" <<'UNIT'
      [Timer]
      OnCalendar=
      OnCalendar=daily
      RandomizedDelaySec=30min
      UNIT
            incus exec ubuntu-2404 -- systemctl daemon-reload
            incus exec ubuntu-2404 -- systemctl enable --now fstrim.timer

            # 게스트 → mac-studio 직접 백업 (2026-10-22). 호스트(server2) 스냅샷/중간 저장 없이
            # 게스트 안의 restic 이 tailnet 으로 바로 보낸다. 변경분만 전송(dedup)하고 저장소엔
            # 최신 1개만 남긴다. 호스트→tailnet 경로는 ubuntu-2404-proxy LXC 의 masquerade
            # (hosts/_lib/incus-tailscale-proxy.nix egressEnsure)가 열어 준다.
            # 대상 제외: docker 이미지/빌드캐시/컨테이너 로그, node_modules, 앱이 매일 만드는 DB 덤프
            # 중 최신 1개를 뺀 나머지(/srv/b2g24/backup 에 15일치 ~170GiB).
            if ! incus exec ubuntu-2404 -- which restic &>/dev/null; then
              incus exec ubuntu-2404 -- apt-get install -y restic
            fi
            for f in ssh-key restic-password; do
              if [ -f "/var/lib/nix-secrets/backup/$f" ]; then
                incus file push "/var/lib/nix-secrets/backup/$f" "ubuntu-2404/root/.backup/$f" \
                  --create-dirs --uid 0 --gid 0 --mode 0600
              fi
            done
            incus exec ubuntu-2404 -- bash -c "cat > /usr/local/sbin/backup-to-macstudio && chmod 755 /usr/local/sbin/backup-to-macstudio" <<'SCRIPT'
      #!/bin/bash
      set -euo pipefail
      # mac-studio 는 게스트 DNS(1.1.1.1)로 MagicDNS 이름을 못 풀어서 tailnet IP 를 쓴다.
      export RESTIC_REPOSITORY="sftp:bitstep@100.64.0.15:/Users/bitstep/backups/ubuntu-2404-guest"
      export RESTIC_PASSWORD_FILE=/root/.backup/restic-password
      # systemd 서비스에는 HOME 이 없어 restic 캐시를 못 열고 매번 느려진다.
      export XDG_CACHE_HOME=/var/cache
      SSH_ARGS="-i /root/.backup/ssh-key -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null"
      restic() { /usr/bin/restic -o "sftp.args=$SSH_ARGS" "$@"; }

      DUMP_DIR=/srv/b2g24/backup
      EXCL=$(mktemp)
      trap 'rm -f "$EXCL"' EXIT
      # 30분 이내에 수정된 덤프는 쓰는 중일 수 있어 완성본으로 안 친다.
      # LATEST 가 비어 있으면 *.archive.gz 가 전부 제외되도록 -name 으로 한정한다(전체 15일치 방지).
      LATEST=$(find "$DUMP_DIR" -maxdepth 1 -name 'jodal_insight-*.archive.gz' -mmin +30 -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-)
      find "$DUMP_DIR" -maxdepth 1 -type f -name '*.archive.gz' ! -path "$LATEST" > "$EXCL"

      restic snapshots &>/dev/null || restic init

      # 종료코드 3 = 일부 파일을 못 읽음(실행 중 사라진 파일 등) → 스냅샷은 만들어졌으니 경고로만 취급
      rc=0
      restic backup --one-file-system --exclude-file "$EXCL" \
        --exclude node_modules --exclude /root/.backup \
        /home /root /etc /srv /var/lib/docker/volumes || rc=$?
      if [ "$rc" -ne 0 ] && [ "$rc" -ne 3 ]; then exit "$rc"; fi

      # 최신 1개만 보관. 경로 집합이 같아 한 그룹이지만 만일을 위해 host 기준으로 묶는다.
      restic forget --keep-last 1 --group-by host --prune --quiet
      SCRIPT
            incus exec ubuntu-2404 -- bash -c "cat > /etc/systemd/system/backup-to-macstudio.service" <<'UNIT'
      [Unit]
      Description=Back up this VM directly to mac-studio (restic, keep latest 1)
      After=network-online.target docker.service
      Wants=network-online.target

      [Service]
      Type=oneshot
      ExecStart=/usr/local/sbin/backup-to-macstudio
      Nice=10
      IOSchedulingClass=idle
      UNIT
            incus exec ubuntu-2404 -- bash -c "cat > /etc/systemd/system/backup-to-macstudio.timer" <<'UNIT'
      [Unit]
      Description=Daily backup to mac-studio

      [Timer]
      # 게스트 시간대는 UTC. 앱 DB 덤프(04:00 시작, ~30분 소요) 이후로 잡는다.
      OnCalendar=*-*-* 06:00:00
      Persistent=true
      RandomizedDelaySec=15min

      [Install]
      WantedBy=timers.target
      UNIT
            incus exec ubuntu-2404 -- systemctl daemon-reload
            incus exec ubuntu-2404 -- systemctl enable --now backup-to-macstudio.timer
    '';
  };
}
