{
  pkgs,
  lib,
  ...
}: {
  systemd.services.incus-create-genple-dev = {
    description = "Create genple-dev Alpine LXC if not exists";
    after = ["incus-startup.service" "systemd-networkd.service"];
    requires = ["incus-startup.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      if incus info genple-dev &>/dev/null; then
        exit 0
      fi

      if ! incus remote list --format=csv | cut -d, -f1 | grep -qx "images"; then
        incus remote add images https://images.linuxcontainers.org \
          --protocol=simplestreams --public
      fi

      incus launch images:alpine/3.21 genple-dev -c security.nesting=true

      sleep 2
      incus stop genple-dev --force 2>/dev/null || true

      # br-lan macvlan — incus 6.x는 unmanaged bridge에 veth 미부착
      incus config device remove genple-dev eth0 2>/dev/null || true
      incus config device add genple-dev eth0 nic nictype=macvlan parent=br-lan mtu=1400

      incus start genple-dev
    '';
  };

  systemd.services.incus-setup-genple-dev = {
    description = "Setup Docker, tailscale in genple-dev LXC";
    after = ["incus-create-genple-dev.service"];
    requires = ["incus-create-genple-dev.service"];
    partOf = ["incus-create-genple-dev.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "180";
    };
    script = ''
      # Docker 이미 실행 중이면 건너뜀
      if incus exec genple-dev -- docker info &>/dev/null; then
        exit 0
      fi

      for i in $(seq 1 24); do
        incus exec genple-dev -- true 2>/dev/null && break
        sleep 5
      done
      if ! incus exec genple-dev -- true 2>/dev/null; then
        echo "genple-dev: exec not ready after 120s" >&2
        exit 1
      fi

      # eth0 DHCP IP 대기
      for i in $(seq 1 12); do
        incus exec genple-dev -- ip addr show eth0 2>/dev/null | grep -q 'inet ' && break
        sleep 5
      done
      if ! incus exec genple-dev -- ip addr show eth0 2>/dev/null | grep -q 'inet '; then
        echo "genple-dev: eth0 no IPv4 after 60s" >&2
        exit 1
      fi

      incus exec genple-dev -- apk update -q
      incus exec genple-dev -- apk add --no-cache docker docker-compose openssh tailscale iptables git rsync

      # Docker
      incus exec genple-dev -- rc-update add docker default
      incus exec genple-dev -- rc-service docker start

      # SSH (수동 배포용)
      incus exec genple-dev -- rc-update add sshd default
      incus exec genple-dev -- sh -c 'printf "PermitRootLogin yes\nPasswordAuthentication yes\nPermitEmptyPasswords yes\n" >> /etc/ssh/sshd_config'
      incus exec genple-dev -- passwd -d root
      incus exec genple-dev -- rc-service sshd start

      # IP forwarding (tailscale 필요)
      incus exec genple-dev -- sysctl -w net.ipv4.ip_forward=1
      incus exec genple-dev -- sh -c 'echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-tailscale.conf'

      # tailscale 활성화 (state 없음 — 수동 join 필요)
      incus exec genple-dev -- rc-update add tailscale default
      incus exec genple-dev -- rc-service tailscale start

      echo "genple-dev LXC setup complete" >&2
      echo "  tailscale join: incus exec genple-dev -- tailscale up --login-server https://e.772610158.xyz" >&2
    '';
  };
}
