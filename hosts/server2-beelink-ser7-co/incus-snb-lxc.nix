{
  pkgs,
  lib,
  ...
}: {
  systemd.services.incus-create-snb = {
    description = "Create snb Alpine LXC if not exists";
    after = ["incus-startup.service" "systemd-networkd.service"];
    requires = ["incus-startup.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      if incus info snb &>/dev/null; then
        exit 0
      fi

      if ! incus remote list --format=csv | cut -d, -f1 | grep -qx "images"; then
        incus remote add images https://images.linuxcontainers.org \
          --protocol=simplestreams --public
      fi

      incus launch images:alpine/3.21 snb -c security.nesting=true

      sleep 2
      incus stop snb --force 2>/dev/null || true

      # br-lan macvlan — incus 6.x는 unmanaged bridge에 veth 미부착
      incus config device remove snb eth0 2>/dev/null || true
      incus config device add snb eth0 nic nictype=macvlan parent=br-lan mtu=1400

      incus start snb
    '';
  };

  systemd.services.incus-setup-snb = {
    description = "Setup Docker, tailscale in snb LXC";
    after = ["incus-create-snb.service"];
    requires = ["incus-create-snb.service"];
    partOf = ["incus-create-snb.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "180";
    };
    script = ''
      # Docker 이미 실행 중이면 건너뜀
      if incus exec snb -- docker info &>/dev/null; then
        exit 0
      fi

      for i in $(seq 1 24); do
        incus exec snb -- true 2>/dev/null && break
        sleep 5
      done
      if ! incus exec snb -- true 2>/dev/null; then
        echo "snb: exec not ready after 120s" >&2
        exit 1
      fi

      # eth0 DHCP IP 대기
      for i in $(seq 1 12); do
        incus exec snb -- ip addr show eth0 2>/dev/null | grep -q 'inet ' && break
        sleep 5
      done
      if ! incus exec snb -- ip addr show eth0 2>/dev/null | grep -q 'inet '; then
        echo "snb: eth0 no IPv4 after 60s" >&2
        exit 1
      fi

      incus exec snb -- apk update -q
      incus exec snb -- apk add --no-cache docker docker-compose tailscale iptables git rsync

      # Docker
      incus exec snb -- rc-update add docker default
      incus exec snb -- rc-service docker start

      # IP forwarding (tailscale 필요)
      incus exec snb -- sysctl -w net.ipv4.ip_forward=1
      incus exec snb -- sh -c 'echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-tailscale.conf'

      # tailscale 활성화 (state 없음 — 수동 join 필요)
      incus exec snb -- rc-update add tailscale default
      incus exec snb -- rc-service tailscale start

      echo "snb LXC setup complete" >&2
      echo "  tailscale join: incus exec snb -- tailscale up --login-server https://e.772610158.xyz --hostname=snb" >&2
    '';
  };
}
