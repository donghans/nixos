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
        -c limits.cpu=8 \
        -c limits.memory=32GiB \
        -d root,size=160GiB \
        -d eth0,type=nic,nictype=bridged,parent=br-lan,mtu=1400
    '';
  };

  # VM 생성 후 openssh 설치 (incus exec 방식 — cloud-init 불필요)
  # tailscale은 ubuntu-2404-proxy LXC가 대신 담당
  systemd.services.incus-setup-ubuntu-vm = {
    description = "Setup openssh in Ubuntu 24.04 VM";
    after = ["incus-update-vm-nic-ubuntu-2404.service"];
    requires = ["incus-update-vm-nic-ubuntu-2404.service"];
    wantedBy = ["multi-user.target"];
    path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      TimeoutStartSec = "300";
    };
    script = ''
      # sshd가 이미 설치돼 있으면 건너뜀
      if incus exec ubuntu-2404 -- which sshd &>/dev/null; then
        exit 0
      fi

      # VM agent가 응답할 때까지 대기 (NIC 교체 후 재부팅 시간 포함)
      for i in $(seq 1 36); do
        incus exec ubuntu-2404 -- true 2>/dev/null && break
        sleep 5
      done

      if ! incus exec ubuntu-2404 -- true 2>/dev/null; then
        echo "ubuntu-2404: agent 미응답 — setup 건너뜀" >&2
        exit 1
      fi

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
    '';
  };
}
