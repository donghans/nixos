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
        -d root,size=330GiB \
        -d eth0,type=nic,nictype=bridged,parent=br-lan,mtu=1400
    '';
  };

  # ubuntu-2404 root.img 는 nodatacow(+C) 파일이어야 한다 — 쿼터(qgroup) 한도는 두지 않는다.
  #
  # 이 VM 의 디스크는 읽기/쓰기가 매우 잦다. btrfs 는 CoW 라서 게스트가 작은 블록을 덮어쓸 때마다
  # 새 extent 가 생기고, 큰 extent 의 일부만 참조되면 나머지도 물리 공간을 계속 차지한다.
  # 2026-11-03 실측(compsize): 참조 341GiB 인데 디스크 사용 436GiB(약 95GiB 낭비), extent 약 453만 개
  # (평균 약 75KB). 이 낭비는 스냅샷이 없어도 생기고, qgroup referenced 에도 그대로 잡혀
  # 2026-09-28·10-21 에 한도(EDQUOT)를, 10-30 에는 호스트 디스크(ENOSPC)를 채워 VM 이 멈췄다.
  # 한도를 올리는 건 미봉책이었다(256 → 400 → 450 → 520GiB).
  #
  # 근본 해결: root.img 를 +C(nodatacow)로 다시 만들어 덮어쓰기를 제자리에서 하게 한다 → 쪼개짐·낭비가 안 생긴다.
  # 게스트에는 같은 virtio 디스크로 보이므로 게스트 안 동작은 바뀌지 않는다(대가: 이 파일에 한해
  # btrfs 체크섬·압축이 없다. 스냅샷을 쓰지 않으므로 문제 없음). +C 는 "빈 파일"에서만 켤 수 있어서
  # 이미 데이터가 있는 파일에는 못 건다 — VM 을 새로 만들 땐 root.img 를 비운 채 chattr +C 후 채워야 한다
  # (확인: lsattr .../virtual-machines/ubuntu-2404/root.img 에 C 가 있어야 함).
  # 수동 한도는 `btrfs qgroup limit none` 으로 해제했다(2026-11-03).
  #
  # 2026-11-05 디스크를 450GiB → 330GiB 로 줄였다(사용자 결정: 담당자가 Docker/로그를 직접 정리하게 하려는 상한 축소).
  # 방식: 새 VM 을 정식 330GiB 로 만들고 정지한 원본에서 사용 블록만 복제·축소한 뒤 이름을 맞바꿨다(설정=실제 크기).
  # 게스트 df 320G(사용 약 273G, 여유 약 48G). 이전 VM 은 ubuntu-2404-old 로 남겼고 mac-studio 에도 보관했다.
  # 주의: `incus config device set ubuntu-2404 root size=…` 는 쓰지 말 것 — 값이 바뀌면 incus 가 qgroup 한도(referenced)를
  # 다시 걸어 게스트 여유가 남아도 EDQUOT 로 VM 이 멈춘다(위 9-28·10-21 과 같은 함정). 크기를 또 바꿀 때는 새 VM 복제 방식으로.

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
            # 게스트 안의 restic 이 tailnet 으로 바로 보낸다. 변경분만 전송(dedup)한다. 보관은
            # 「건강한(ok) 스냅샷 기준 일 7 + 주 3」(2026-11-05; 이전엔 최신 1개뿐이라 망가진 날의
            # 백업이 마지막 정상본을 덮어썼다). 호스트→tailnet 경로는 ubuntu-2404-proxy LXC 의 masquerade
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
      # ServerAlive: mac-studio 와 연결이 끊긴 채 무한 대기하는 사고(2026-10-24 lxc-backup 이 10일간 멈춤)를
      # 막는다 — 응답 없는 연결은 약 2분(30초×4) 안에 끊긴다. ConnectTimeout 은 접속 대기 상한.
      SSH_ARGS="-i /root/.backup/ssh-key -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=30 -o ServerAliveCountMax=4 -o ConnectTimeout=30"
      restic() { /usr/bin/restic -o "sftp.args=$SSH_ARGS" "$@"; }

      DUMP_DIR=/srv/b2g24/backup
      EXCL=$(mktemp)
      trap 'rm -f "$EXCL"' EXIT
      # 30분 이내에 수정된 덤프는 쓰는 중일 수 있어 완성본으로 안 친다.
      # LATEST 가 비어 있으면 *.archive.gz 가 전부 제외되도록 -name 으로 한정한다(전체 15일치 방지).
      LATEST=$(find "$DUMP_DIR" -maxdepth 1 -name 'jodal_insight-*.archive.gz' -mmin +30 -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-)
      find "$DUMP_DIR" -maxdepth 1 -type f -name '*.archive.gz' ! -path "$LATEST" > "$EXCL"

      restic snapshots &>/dev/null || restic init
      # 비정상 종료(kill/재부팅)가 남긴 오래된 잠금만 제거한다 — 잠금이 남으면 뒤의 forget 이 계속 실패한다.
      restic unlock

      # 건강 신호(인프라 수준만). 하나라도 걸리면 이 스냅샷에 suspect 태그를 붙인다 — 백업은 그대로 한다.
      # 보관 규칙이 ok 스냅샷만 세므로 나쁜 날이 좋은 스냅샷을 밀어내지 못한다. 앱이 잘못된 데이터를
      # 정상처럼 쓴 논리적 손상은 여기서 못 잡는다(보관 기간이 대신 막는다).
      STATE=ok
      WHY=""
      note() { STATE=suspect; WHY="$WHY $1"; }
      USE=$(df --output=pcent / | tail -1 | tr -dc 0-9)
      [ "$USE" -lt 95 ] || note "disk-$USE%"
      systemctl is-active --quiet docker || note "docker-inactive"
      if [ -n "$LATEST" ]; then
        AGE=$(( $(date +%s) - $(stat -c %Y "$LATEST") ))
        [ "$AGE" -lt 108000 ] || note "dump-age-$AGE"
        # 직전 덤프 3개 평균의 70% 미만이면 잘린 덤프로 본다.
        PREV=$(find "$DUMP_DIR" -maxdepth 1 -name 'jodal_insight-*.archive.gz' ! -path "$LATEST" -printf '%T@ %s\n' | sort -n | tail -3 | awk '{s+=$2;n++} END{if(n)print int(s/n)}')
        SZ=$(stat -c %s "$LATEST")
        if [ -n "$PREV" ] && [ "$SZ" -lt $(( PREV * 70 / 100 )) ]; then note "dump-small"; fi
      else
        note "dump-missing"
      fi

      # 종료코드 3 = 일부 파일을 못 읽음(실행 중 사라진 파일 등) → 스냅샷은 만들어졌으니 경고로만 취급
      rc=0
      restic backup --one-file-system --tag "$STATE" --exclude-file "$EXCL" \
        --exclude node_modules --exclude /root/.backup \
        /home /root /etc /srv /var/lib/docker/volumes || rc=$?
      if [ "$rc" -ne 0 ] && [ "$rc" -ne 3 ]; then exit "$rc"; fi

      # 보관: ok 스냅샷 기준 일 7 + 주 3, suspect 는 14일. 경로 집합이 같아 한 그룹이지만 host 기준으로 묶는다.
      # (태그 없는 옛 스냅샷 1개는 이 규칙에 안 걸려 남는다 — 확인 후 수동 삭제.)
      restic forget --tag ok --keep-daily 7 --keep-weekly 3 --group-by host --quiet
      restic forget --tag suspect --keep-within 14d --group-by host --quiet
      # prune 은 무겁고 저장소 락을 오래 잡으므로 일요일(게스트 UTC)에만 한다. 이때 저장소 일부도 읽어 점검한다.
      if [ "$(date +%u)" = 7 ]; then
        restic prune --quiet
        restic check --read-data-subset=2% --quiet
      fi
      # suspect 면 서비스를 실패로 끝내 systemctl --failed 에 보이게 한다.
      if [ "$STATE" != ok ]; then echo "suspect:$WHY" >&2; exit 4; fi
      SCRIPT
            incus exec ubuntu-2404 -- bash -c "cat > /etc/systemd/system/backup-to-macstudio.service" <<'UNIT'
      [Unit]
      Description=Back up this VM directly to mac-studio (restic, ok daily 7 + weekly 3)
      After=network-online.target docker.service
      Wants=network-online.target

      [Service]
      Type=oneshot
      ExecStart=/usr/local/sbin/backup-to-macstudio
      # oneshot 의 기본 시작 제한은 무제한이라 멈추면 영원히 activating 이다. 평소 약 12분(2026-10-26 실측).
      TimeoutStartSec=6h
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
