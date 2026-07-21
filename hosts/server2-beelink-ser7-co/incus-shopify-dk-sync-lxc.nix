{
  pkgs,
  lib,
  ...
}: let
  ghaDeployPubkey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIE+wohrKeeEb5wnwgBuIQKl8EevQxtERTgnhzikTMdCm gha-deploy@shopify-dk-sync";
in {
  systemd.services.incus-create-shopify-dk-sync = {
    description = "Create shopify-dk-sync Alpine LXC if not exists";
    after = ["incus-startup.service" "systemd-networkd.service"];
    requires = ["incus-startup.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      if incus info shopify-dk-sync &>/dev/null; then
        exit 0
      fi

      if ! incus remote list --format=csv | cut -d, -f1 | grep -qx "images"; then
        incus remote add images https://images.linuxcontainers.org \
          --protocol=simplestreams --public
      fi

      incus launch images:alpine/3.21 shopify-dk-sync -c security.nesting=true

      sleep 2
      incus stop shopify-dk-sync --force 2>/dev/null || true

      # br-lan macvlan — incus 6.x는 unmanaged bridge에 veth 미부착
      incus config device remove shopify-dk-sync eth0 2>/dev/null || true
      incus config device add shopify-dk-sync eth0 nic nictype=macvlan parent=br-lan mtu=1400

      incus start shopify-dk-sync
    '';
  };

  systemd.services.incus-setup-shopify-dk-sync = {
    description = "Setup Docker, tailscale in shopify-dk-sync LXC";
    after = ["incus-create-shopify-dk-sync.service"];
    requires = ["incus-create-shopify-dk-sync.service"];
    partOf = ["incus-create-shopify-dk-sync.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "180";
    };
    script = ''
      # Docker 이미 실행 중이면 건너뜀
      if incus exec shopify-dk-sync -- docker info &>/dev/null; then
        exit 0
      fi

      for i in $(seq 1 24); do
        incus exec shopify-dk-sync -- true 2>/dev/null && break
        sleep 5
      done
      if ! incus exec shopify-dk-sync -- true 2>/dev/null; then
        echo "shopify-dk-sync: exec not ready after 120s" >&2
        exit 1
      fi

      # eth0 DHCP IP 대기
      for i in $(seq 1 12); do
        incus exec shopify-dk-sync -- ip addr show eth0 2>/dev/null | grep -q 'inet ' && break
        sleep 5
      done
      if ! incus exec shopify-dk-sync -- ip addr show eth0 2>/dev/null | grep -q 'inet '; then
        echo "shopify-dk-sync: eth0 no IPv4 after 60s" >&2
        exit 1
      fi

      incus exec shopify-dk-sync -- apk update -q
      incus exec shopify-dk-sync -- apk add --no-cache docker docker-compose openssh tailscale iptables git

      # Docker
      incus exec shopify-dk-sync -- rc-update add docker default
      incus exec shopify-dk-sync -- rc-service docker start

      # SSH (수동 배포용 — 비밀번호 없이 접속, GHA는 아래 전용 배포 키로 접속)
      incus exec shopify-dk-sync -- rc-update add sshd default
      incus exec shopify-dk-sync -- sh -c 'printf "PermitRootLogin yes\nPasswordAuthentication yes\nPermitEmptyPasswords yes\n" >> /etc/ssh/sshd_config'
      incus exec shopify-dk-sync -- passwd -d root
      incus exec shopify-dk-sync -- sh -c 'mkdir -p /root/.ssh && chmod 700 /root/.ssh'
      incus exec shopify-dk-sync -- sh -c 'grep -qxF "${ghaDeployPubkey}" /root/.ssh/authorized_keys 2>/dev/null || echo "${ghaDeployPubkey}" >> /root/.ssh/authorized_keys'
      incus exec shopify-dk-sync -- chmod 600 /root/.ssh/authorized_keys
      incus exec shopify-dk-sync -- rc-service sshd start

      # IP forwarding (tailscale 필요)
      incus exec shopify-dk-sync -- sysctl -w net.ipv4.ip_forward=1
      incus exec shopify-dk-sync -- sh -c 'echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-tailscale.conf'

      # tailscale 활성화 (state 없음 — 수동 join 필요)
      incus exec shopify-dk-sync -- rc-update add tailscale default
      incus exec shopify-dk-sync -- rc-service tailscale start

      echo "shopify-dk-sync LXC setup complete" >&2
      echo "  tailscale join: incus exec shopify-dk-sync -- tailscale up --login-server https://e.772610158.xyz" >&2
    '';
  };
}
