{
  pkgs,
  lib,
  ...
}: {
  systemd.services.incus-create-adx = {
    description = "Create adx Alpine LXC if not exists";
    after = ["incus-startup.service" "systemd-networkd.service"];
    requires = ["incus-startup.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      if incus info adx &>/dev/null; then
        exit 0
      fi

      if ! incus remote list --format=csv | cut -d, -f1 | grep -qx "images"; then
        incus remote add images https://images.linuxcontainers.org \
          --protocol=simplestreams --public
      fi

      incus launch images:alpine/3.21 adx -c security.nesting=true

      sleep 2
      incus stop adx --force 2>/dev/null || true

      # br-lan macvlan — incus 6.x는 unmanaged bridge에 veth 미부착
      incus config device remove adx eth0 2>/dev/null || true
      incus config device add adx eth0 nic nictype=macvlan parent=br-lan mtu=1400

      incus start adx
    '';
  };

  systemd.services.incus-setup-adx = {
    description = "Setup Docker, tailscale in adx LXC";
    after = ["incus-create-adx.service"];
    requires = ["incus-create-adx.service"];
    partOf = ["incus-create-adx.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "180";
    };
    script = ''
      # Docker 이미 실행 중이면 건너뜀
      if incus exec adx -- docker info &>/dev/null; then
        exit 0
      fi

      for i in $(seq 1 24); do
        incus exec adx -- true 2>/dev/null && break
        sleep 5
      done
      if ! incus exec adx -- true 2>/dev/null; then
        echo "adx: exec not ready after 120s" >&2
        exit 1
      fi

      # eth0 DHCP IP 대기
      for i in $(seq 1 12); do
        incus exec adx -- ip addr show eth0 2>/dev/null | grep -q 'inet ' && break
        sleep 5
      done
      if ! incus exec adx -- ip addr show eth0 2>/dev/null | grep -q 'inet '; then
        echo "adx: eth0 no IPv4 after 60s" >&2
        exit 1
      fi

      incus exec adx -- apk update -q
      incus exec adx -- apk add --no-cache docker docker-compose openssh tailscale iptables git

      # Docker
      incus exec adx -- rc-update add docker default
      incus exec adx -- rc-service docker start

      # SSH (수동 배포용)
      incus exec adx -- rc-update add sshd default
      incus exec adx -- sh -c 'printf "PermitRootLogin yes\nPasswordAuthentication yes\nPermitEmptyPasswords yes\n" >> /etc/ssh/sshd_config'
      incus exec adx -- rc-service sshd start

      # IP forwarding (tailscale 필요)
      incus exec adx -- sysctl -w net.ipv4.ip_forward=1
      incus exec adx -- sh -c 'echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-tailscale.conf'

      # tailscale 활성화 (state 없음 — 수동 join 필요)
      incus exec adx -- rc-update add tailscale default
      incus exec adx -- rc-service tailscale start

      echo "adx LXC setup complete" >&2
      echo "  tailscale join: incus exec adx -- tailscale up --login-server https://e.772610158.xyz" >&2
    '';
  };
}
