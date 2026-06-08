{
  pkgs,
  lib,
  ...
}: let
  instanceName = "lightsail-headscale-proxy";
  staticIpName = "lightsail-headscale-proxy-ip";
  keyPairName = "lightsail-headscale-proxy-keypair";
  bundle = "nano_3_0";
  blueprint = "amazon_linux_2023";
  region = "ap-northeast-2";

  headscaleUrl = "https://e.772610158.xyz";

  lightsailSshKey = "/var/lib/nix-secrets/lightsail/ssh-key";
  lightsailUser = "ec2-user";
  tsStatePath = "/var/lib/nix-secrets/lightsail/ts-state";

  # pub 파일은 derivation으로 nix store에 포함 (Lightsail 키페어 import용)
  lightsailPubKey =
    pkgs.writeText "lightsail-headscale-proxy.pub"
    (builtins.readFile ../_deploy/lightsail-headscale-proxy.pub);
in {
  # wantedBy 없음 — activation에서 분리, headscale ExecStartPost에서 비동기 트리거
  systemd.services.lightsail-proxy-sync = {
    description = "Lightsail headscale-proxy lifecycle sync";
    after = ["network-online.target" "headscale.service"];
    wants = ["network-online.target"];
    unitConfig.ConditionPathExists = [lightsailSshKey tsStatePath];
    path = [pkgs.awscli2 pkgs.headscale pkgs.jq pkgs.iproute2 pkgs.openssh];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart =
        pkgs.writeShellScript "lightsail-proxy-sync"
        (builtins.readFile ./lightsail-proxy-sync.sh);
      Environment = [
        "INSTANCE_NAME=${instanceName}"
        "STATIC_IP_NAME=${staticIpName}"
        "KEY_PAIR_NAME=${keyPairName}"
        "BUNDLE=${bundle}"
        "BLUEPRINT=${blueprint}"
        "REGION=${region}"
        "HEADSCALE_URL=${headscaleUrl}"
        "LIGHTSAIL_SSH_KEY=${lightsailSshKey}"
        "LIGHTSAIL_PUB_KEY=${lightsailPubKey}"
        "LIGHTSAIL_USER=${lightsailUser}"
        "TS_STATE=${tsStatePath}"
      ];
    };
  };

  # headscale 시작 후 lightsail-proxy-sync를 비동기로 트리거
  systemd.services.headscale.serviceConfig.ExecStartPost =
    lib.mkAfter "${pkgs.bash}/bin/bash -c 'systemctl start lightsail-proxy-sync.service --no-block || true'";

  # nix-secrets가 root:root 600으로 생성하므로 권한 교정
  systemd.tmpfiles.rules = [
    "z ${lightsailSshKey} 0600 root root -"
    "z ${tsStatePath} 0600 root root -"
  ];
}
