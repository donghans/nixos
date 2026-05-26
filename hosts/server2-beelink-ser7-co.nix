{
  mkHostConfiguration,
  pkgs,
  lib,
  ...
}:
mkHostConfiguration (_: {
  os = {
    # tailscale 모듈 옵션 (문자열이라 toConfig 제약으로 toml 경유 불가 → nix에서 직접 설정)
    mods.sys.services.tailscale = {
      preauthUser = "system";
      preauthName = "exitscale";
      preauthLoginServer = "https://e.772610158.xyz";
      advertiseExitNode = true;
      advertiseRoutes = ["192.168.11.0/24"];
    };

    # ubuntu:24.04는 cloud-init 미포함 미니멀 이미지 → incus exec으로 직접 설치
    systemd.services.incus-create-ubuntu-vm = {
      description = "Create Ubuntu 24.04 Incus VM if not exists";
      after = ["incus-startup.service"];
      requires = ["incus-startup.service"];
      wantedBy = ["multi-user.target"];
      path = [pkgs.incus pkgs.curl pkgs.coreutils];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
        if incus info ubuntu-2404 &>/dev/null; then
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
          -d root,size=160GiB
      '';
    };

    # VM 생성 후 openssh + tailscale 설치 (incus exec 방식 — cloud-init 불필요)
    systemd.services.incus-setup-ubuntu-vm = {
      description = "Setup openssh and tailscale in Ubuntu 24.04 VM";
      after = ["incus-create-ubuntu-vm.service"];
      requires = ["incus-create-ubuntu-vm.service"];
      wantedBy = ["multi-user.target"];
      path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
        # IP 확보까지 최대 3분 대기
        TimeoutStartSec = "180";
      };
      script = ''
        # 이미 설치됐으면 건너뜀
        if incus exec ubuntu-2404 -- which tailscale &>/dev/null; then
          exit 0
        fi

        # VM이 IP를 받을 때까지 대기 (최대 120초)
        for i in $(seq 1 24); do
          IP=$(incus list ubuntu-2404 --format=csv -c4 2>/dev/null | grep -oE '([0-9]+\.){3}[0-9]+' | head -1)
          [ -n "$IP" ] && break
          sleep 5
        done

        if [ -z "''${IP:-}" ]; then
          echo "ubuntu-2404: IP 미확보 — setup 건너뜀" >&2
          exit 1
        fi

        # openssh 설치 + 활성화
        # PermitEmptyPasswords yes: tailscale이 인증 레이어이므로 VM 패스워드 불필요
        incus exec ubuntu-2404 -- apt-get update -qq
        incus exec ubuntu-2404 -- apt-get install -y openssh-server
        incus exec ubuntu-2404 -- bash -c "
          sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
          sed -i 's/^#\?PermitEmptyPasswords.*/PermitEmptyPasswords yes/' /etc/ssh/sshd_config
          passwd -d ubuntu
          systemctl enable --now ssh
          systemctl reload ssh
        "

        # tailscale 설치
        incus exec ubuntu-2404 -- sh -c \
          "curl -fsSL https://tailscale.com/install.sh | sh"

        # preauth key가 있으면 tailscale 인증
        PREAUTH_KEY_FILE="/var/lib/nix-secrets/tailscale/system/devserver.preauth-key"
        if [ -f "$PREAUTH_KEY_FILE" ]; then
          PREAUTH_KEY=$(cat "$PREAUTH_KEY_FILE")
          incus exec ubuntu-2404 -- tailscale up \
            --authkey="$PREAUTH_KEY" \
            --login-server="https://e.772610158.xyz" \
            --accept-routes
        fi
      '';
    };
  };
  hm = {};
})
