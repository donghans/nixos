# dms(document management system) 배포용 빈 Ubuntu LXC — 실제 서비스(web/api/onlyoffice/
# converter)는 다른 작업자가 채워넣는다. 다른 컨테이너들(zupzup 등)과 달리 Alpine이 아니라
# Ubuntu 이미지를 쓰는 이유는 그 작업자의 편의(apt 기반 배포 스크립트 등) 때문.
# 도메인 연결은 incus-dms-tls.nix 참고 (headscale-vps Caddy가 tailscale IP로 reverse_proxy).
{
  pkgs,
  lib,
  ...
}: {
  systemd.services.incus-create-dms = {
    description = "Create dms Ubuntu LXC if not exists";
    after = ["incus-startup.service" "systemd-networkd.service"];
    requires = ["incus-startup.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      if incus info dms &>/dev/null; then
        exit 0
      fi

      if ! incus remote list --format=csv | cut -d, -f1 | grep -qx "images"; then
        incus remote add images https://images.linuxcontainers.org \
          --protocol=simplestreams --public
      fi

      incus launch images:ubuntu/24.04 dms -c security.nesting=true

      sleep 2
      incus stop dms --force 2>/dev/null || true

      # br-lan macvlan — incus 6.x는 unmanaged bridge에 veth 미부착
      incus config device remove dms eth0 2>/dev/null || true
      incus config device add dms eth0 nic nictype=macvlan parent=br-lan mtu=1400

      incus start dms
    '';
  };

  systemd.services.incus-setup-dms = {
    description = "Setup Docker, tailscale in dms LXC";
    after = ["incus-create-dms.service"];
    requires = ["incus-create-dms.service"];
    partOf = ["incus-create-dms.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "180";
    };
    script = ''
      # Docker 이미 실행 중이면 건너뜀
      if incus exec dms -- docker info &>/dev/null; then
        exit 0
      fi

      for i in $(seq 1 24); do
        incus exec dms -- true 2>/dev/null && break
        sleep 5
      done
      if ! incus exec dms -- true 2>/dev/null; then
        echo "dms: exec not ready after 120s" >&2
        exit 1
      fi

      # eth0 DHCP IP 대기
      for i in $(seq 1 12); do
        incus exec dms -- ip addr show eth0 2>/dev/null | grep -q 'inet ' && break
        sleep 5
      done
      if ! incus exec dms -- ip addr show eth0 2>/dev/null | grep -q 'inet '; then
        echo "dms: eth0 no IPv4 after 60s" >&2
        exit 1
      fi

      incus exec dms -- apt-get update -qq
      incus exec dms -- apt-get install -y openssh-server iptables git rsync curl

      # Docker — Ubuntu 배포판 docker.io(구버전 고정)가 아니라 docker.com 공식 저장소
      # 사용. incus-ubuntu-vm.nix와 동일한 이유: docker-compose-plugin이 apt 기본
      # 저장소보다 훨씬 최신(예: 2026-09 기준 apt는 2.40.x, 공식 저장소는 5.x)이라
      # 다른 작업자가 최신 compose 문법을 그대로 쓸 수 있게 하기 위함.
      incus exec dms -- bash -c "
        install -m 0755 -d /etc/apt/keyrings
        curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
        chmod a+r /etc/apt/keyrings/docker.asc
        echo \"deb [arch=\$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \$(. /etc/os-release && echo \"\$VERSION_CODENAME\") stable\" \
          > /etc/apt/sources.list.d/docker.list
        apt-get update -qq
        apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
        systemctl enable --now docker
      "

      # SSH (수동 배포용)
      incus exec dms -- sh -c '
        sed -i "s/^#\?PasswordAuthentication.*/PasswordAuthentication yes/" /etc/ssh/sshd_config
        sed -i "s/^#\?PermitEmptyPasswords.*/PermitEmptyPasswords yes/" /etc/ssh/sshd_config
        sed -i "s/^#\?PermitRootLogin.*/PermitRootLogin yes/" /etc/ssh/sshd_config
      '
      incus exec dms -- passwd -d root
      incus exec dms -- systemctl enable --now ssh

      # IP forwarding (tailscale 필요)
      incus exec dms -- sysctl -w net.ipv4.ip_forward=1
      incus exec dms -- sh -c 'echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-tailscale.conf'

      # tailscale 활성화 (state 없음 — 수동 join 필요)
      incus exec dms -- sh -c 'curl -fsSL https://tailscale.com/install.sh | sh'
      incus exec dms -- systemctl enable --now tailscaled

      echo "dms LXC setup complete" >&2
      echo "  tailscale join: incus exec dms -- tailscale up --login-server https://e.772610158.xyz" >&2
    '';
  };
}
