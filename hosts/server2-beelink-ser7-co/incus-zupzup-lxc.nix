# 줍줍랩(zupzup-lab) prod 배포용 LXC — student/teacher/ops(Next.js)+api(Express)+mongo+redis를
# 이 컨테이너 안에서 docker compose로 띄운다. TLS는 이 컨테이너가 하지 않는다 — 도메인
# (member/admin/ops.zupzup.772610158.xyz)이 headscale-vps의 공인 IP를 직접 가리키므로,
# headscale-vps의 Caddy가 그쪽에서 Let's Encrypt HTTP-01로 인증서를 받고 이 컨테이너의
# tailscale IP로 reverse_proxy 한다(genple-demo류 DNS-01 특수case와 다르다).
{
  pkgs,
  lib,
  ...
}: {
  systemd.services.incus-create-zupzup = {
    description = "Create zupzup Alpine LXC if not exists";
    after = ["incus-startup.service" "systemd-networkd.service"];
    requires = ["incus-startup.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      if incus info zupzup &>/dev/null; then
        exit 0
      fi

      if ! incus remote list --format=csv | cut -d, -f1 | grep -qx "images"; then
        incus remote add images https://images.linuxcontainers.org \
          --protocol=simplestreams --public
      fi

      incus launch images:alpine/3.21 zupzup -c security.nesting=true

      sleep 2
      incus stop zupzup --force 2>/dev/null || true

      # br-lan macvlan — incus 6.x는 unmanaged bridge에 veth 미부착
      incus config device remove zupzup eth0 2>/dev/null || true
      incus config device add zupzup eth0 nic nictype=macvlan parent=br-lan mtu=1400

      incus start zupzup
    '';
  };

  systemd.services.incus-setup-zupzup = {
    description = "Setup Docker, tailscale in zupzup LXC";
    after = ["incus-create-zupzup.service"];
    requires = ["incus-create-zupzup.service"];
    partOf = ["incus-create-zupzup.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "180";
    };
    script = ''
      # Docker 이미 실행 중이면 건너뜀
      if incus exec zupzup -- docker info &>/dev/null; then
        exit 0
      fi

      for i in $(seq 1 24); do
        incus exec zupzup -- true 2>/dev/null && break
        sleep 5
      done
      if ! incus exec zupzup -- true 2>/dev/null; then
        echo "zupzup: exec not ready after 120s" >&2
        exit 1
      fi

      # eth0 DHCP IP 대기
      for i in $(seq 1 12); do
        incus exec zupzup -- ip addr show eth0 2>/dev/null | grep -q 'inet ' && break
        sleep 5
      done
      if ! incus exec zupzup -- ip addr show eth0 2>/dev/null | grep -q 'inet '; then
        echo "zupzup: eth0 no IPv4 after 60s" >&2
        exit 1
      fi

      incus exec zupzup -- apk update -q
      incus exec zupzup -- apk add --no-cache docker docker-compose openssh tailscale iptables git rsync

      # Docker
      incus exec zupzup -- rc-update add docker default
      incus exec zupzup -- rc-service docker start

      # SSH (수동 배포용)
      incus exec zupzup -- rc-update add sshd default
      incus exec zupzup -- sh -c 'printf "PermitRootLogin yes\nPasswordAuthentication yes\nPermitEmptyPasswords yes\n" >> /etc/ssh/sshd_config'
      incus exec zupzup -- passwd -d root
      incus exec zupzup -- rc-service sshd start

      # IP forwarding (tailscale 필요)
      incus exec zupzup -- sysctl -w net.ipv4.ip_forward=1
      incus exec zupzup -- sh -c 'echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-tailscale.conf'

      # tailscale 활성화 (state 없음 — 수동 join 필요)
      incus exec zupzup -- rc-update add tailscale default
      incus exec zupzup -- rc-service tailscale start

      echo "zupzup LXC setup complete" >&2
      echo "  tailscale join: incus exec zupzup -- tailscale up --login-server https://e.772610158.xyz" >&2
    '';
  };
}
