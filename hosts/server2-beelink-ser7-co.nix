{
  mkHostConfiguration,
  pkgs,
  ...
}:
mkHostConfiguration (_: {
  os = {
    # tailscale 모듈 옵션 (문자열이라 toConfig 제약으로 toml 경유 불가 → nix에서 직접 설정)
    mods.sys.services.tailscale = {
      preauthUser = "donghans";
      preauthName = "exitscale";
      preauthLoginServer = "https://e.772610158.xyz";
      advertiseExitNode = true;
    };

    systemd.services.incus-create-ubuntu-vm = {
      description = "Create Ubuntu 24.04 Incus VM if not exists";
      after = ["incus-startup.service"];
      requires = ["incus-startup.service"];
      wantedBy = ["multi-user.target"];
      path = [pkgs.incus pkgs.curl];
      serviceConfig = {
        Type = "oneshot";
        RemainAfterExit = true;
      };
      script = ''
                if incus info ubuntu-2404 &>/dev/null; then
                  exit 0
                fi

                PREAUTH_KEY_FILE="/var/lib/nix-secrets/tailscale/donghans/devserver.preauth-key"

                # cloud-init user-data 작성
                CLOUD_INIT=$(cat <<'EOF'
        #cloud-config
        packages:
          - openssh-server
        runcmd:
          - systemctl enable --now ssh
          - curl -fsSL https://tailscale.com/install.sh | sh
        EOF
        )

                # preauth key가 있으면 tailscale up 추가
                if [[ -f "$PREAUTH_KEY_FILE" ]]; then
                  PREAUTH_KEY=$(cat "$PREAUTH_KEY_FILE")
                  CLOUD_INIT="$CLOUD_INIT
          - tailscale up --authkey=$PREAUTH_KEY --login-server=https://e.772610158.xyz --accept-routes"
                fi

                incus launch ubuntu:24.04 ubuntu-2404 --vm \
                  -c limits.cpu=8 \
                  -c limits.memory=32GiB \
                  -d root,size=160GiB \
                  -c "user.user-data=$CLOUD_INIT"
      '';
    };
  };
  hm = {};
})
