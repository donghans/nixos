{
  pkgs,
  lib,
  ...
}: {
  systemd.services.incus-create-genple-demo = {
    description = "Create genple-demo Alpine LXC if not exists";
    after = ["incus-startup.service" "systemd-networkd.service"];
    requires = ["incus-startup.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      if incus info genple-demo &>/dev/null; then
        exit 0
      fi

      if ! incus remote list --format=csv | cut -d, -f1 | grep -qx "images"; then
        incus remote add images https://images.linuxcontainers.org \
          --protocol=simplestreams --public
      fi

      incus launch images:alpine/3.21 genple-demo -c security.nesting=true

      sleep 2
      incus stop genple-demo --force 2>/dev/null || true

      # br-lan macvlan — incus 6.x는 unmanaged bridge에 veth 미부착
      incus config device remove genple-demo eth0 2>/dev/null || true
      incus config device add genple-demo eth0 nic nictype=macvlan parent=br-lan mtu=1400

      incus start genple-demo
    '';
  };

  systemd.services.incus-setup-genple-demo = {
    description = "Setup Docker, tailscale in genple-demo LXC";
    after = ["incus-create-genple-demo.service"];
    requires = ["incus-create-genple-demo.service"];
    partOf = ["incus-create-genple-demo.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "180";
    };
    script = ''
      # Docker 이미 실행 중이면 건너뜀
      if incus exec genple-demo -- docker info &>/dev/null; then
        exit 0
      fi

      for i in $(seq 1 24); do
        incus exec genple-demo -- true 2>/dev/null && break
        sleep 5
      done
      if ! incus exec genple-demo -- true 2>/dev/null; then
        echo "genple-demo: exec not ready after 120s" >&2
        exit 1
      fi

      # eth0 DHCP IP 대기
      for i in $(seq 1 12); do
        incus exec genple-demo -- ip addr show eth0 2>/dev/null | grep -q 'inet ' && break
        sleep 5
      done
      if ! incus exec genple-demo -- ip addr show eth0 2>/dev/null | grep -q 'inet '; then
        echo "genple-demo: eth0 no IPv4 after 60s" >&2
        exit 1
      fi

      incus exec genple-demo -- apk update -q
      incus exec genple-demo -- apk add --no-cache docker docker-compose openssh tailscale iptables git rsync

      # Docker
      incus exec genple-demo -- rc-update add docker default
      incus exec genple-demo -- rc-service docker start

      # SSH (수동 배포용)
      incus exec genple-demo -- rc-update add sshd default
      incus exec genple-demo -- sh -c 'printf "PermitRootLogin yes\nPasswordAuthentication yes\nPermitEmptyPasswords yes\n" >> /etc/ssh/sshd_config'
      incus exec genple-demo -- passwd -d root
      incus exec genple-demo -- rc-service sshd start

      # IP forwarding (tailscale 필요)
      incus exec genple-demo -- sysctl -w net.ipv4.ip_forward=1
      incus exec genple-demo -- sh -c 'echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-tailscale.conf'

      # tailscale 활성화 (state 없음 — 수동 join 필요)
      incus exec genple-demo -- rc-update add tailscale default
      incus exec genple-demo -- rc-service tailscale start

      echo "genple-demo LXC setup complete" >&2
      echo "  tailscale join: incus exec genple-demo -- tailscale up --login-server https://e.772610158.xyz" >&2
    '';
  };
}
