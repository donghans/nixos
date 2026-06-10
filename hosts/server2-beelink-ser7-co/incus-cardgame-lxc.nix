{
  pkgs,
  lib,
  ...
}: let
  stateFile = "/var/lib/nix-secrets/tailscale/system/cardgame.state";
in {
  systemd.services.incus-create-cardgame = {
    description = "Create cardgame Alpine LXC if not exists";
    after = ["incus-startup.service" "systemd-networkd.service"];
    requires = ["incus-startup.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
    };
    script = ''
      if incus info cardgame &>/dev/null; then
        exit 0
      fi

      if ! incus remote list --format=csv | cut -d, -f1 | grep -qx "images"; then
        incus remote add images https://images.linuxcontainers.org \
          --protocol=simplestreams --public
      fi

      incus launch images:alpine/3.21 cardgame -c security.nesting=true

      sleep 2
      incus stop cardgame --force 2>/dev/null || true

      # br-lan macvlan — incus 6.x는 unmanaged bridge에 veth 미부착
      incus config device remove cardgame eth0 2>/dev/null || true
      incus config device add cardgame eth0 nic nictype=macvlan parent=br-lan mtu=1400

      incus start cardgame
    '';
  };

  systemd.services.incus-setup-cardgame = {
    description = "Setup Node.js, MariaDB, tailscale in cardgame LXC";
    after = ["incus-create-cardgame.service"];
    requires = ["incus-create-cardgame.service"];
    partOf = ["incus-create-cardgame.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "180";
    };
    script = ''
      # tailscale 이미 실행 중이면 건너뜀
      if incus exec cardgame -- tailscale status --json 2>/dev/null | grep -q '"BackendState":"Running"'; then
        exit 0
      fi

      for i in $(seq 1 24); do
        incus exec cardgame -- true 2>/dev/null && break
        sleep 5
      done
      if ! incus exec cardgame -- true 2>/dev/null; then
        echo "cardgame: exec not ready after 120s" >&2
        exit 1
      fi

      # eth0 DHCP IP 대기
      for i in $(seq 1 12); do
        incus exec cardgame -- ip addr show eth0 2>/dev/null | grep -q 'inet ' && break
        sleep 5
      done
      if ! incus exec cardgame -- ip addr show eth0 2>/dev/null | grep -q 'inet '; then
        echo "cardgame: eth0 no IPv4 after 60s" >&2
        exit 1
      fi

      incus exec cardgame -- apk update -q
      incus exec cardgame -- apk add --no-cache nodejs npm mariadb mariadb-client openssh tailscale iptables

      # MariaDB 초기화
      incus exec cardgame -- mysql_install_db --user=mysql --datadir=/var/lib/mysql
      incus exec cardgame -- rc-update add mariadb default
      incus exec cardgame -- rc-service mariadb start

      # SSH (수동 배포용)
      incus exec cardgame -- rc-update add sshd default
      incus exec cardgame -- sh -c 'printf "PermitRootLogin yes\nPasswordAuthentication yes\nPermitEmptyPasswords yes\n" >> /etc/ssh/sshd_config'
      incus exec cardgame -- passwd -d root
      incus exec cardgame -- rc-service sshd start

      # IP forwarding (tailscale 필요)
      incus exec cardgame -- sysctl -w net.ipv4.ip_forward=1
      incus exec cardgame -- sh -c 'echo "sysctl -w net.ipv4.ip_forward=1" > /etc/local.d/tailscale.start'
      incus exec cardgame -- chmod +x /etc/local.d/tailscale.start
      incus exec cardgame -- rc-update add local default

      # tailscale 활성화
      incus exec cardgame -- rc-update add tailscale default

      if [ -f "${stateFile}" ]; then
        incus exec cardgame -- mkdir -p /var/lib/tailscale
        incus file push "${stateFile}" cardgame/var/lib/tailscale/tailscaled.state \
          --uid 0 --gid 0 --mode 0600
        incus exec cardgame -- rc-service tailscale start
        incus exec cardgame -- tailscale set --hostname="cardgame"
      else
        echo "WARNING: tailscale stateFile not found — manual join required" >&2
        echo "  Run: incus exec cardgame -- tailscale up --login-server https://e.772610158.xyz" >&2
        incus exec cardgame -- rc-service tailscale start
      fi
    '';
  };
}
