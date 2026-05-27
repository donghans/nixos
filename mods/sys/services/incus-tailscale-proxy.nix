{lib, pkgs, config, ...}:
let
  cfg = config.mods.sys.services."incus-tailscale-proxy";

  mkProxyConfig = name: proxyCfg:
    let
      lxcName = "${name}-proxy";
    in {
      systemd.network.netdevs."10-${proxyCfg.internalBridge}" = {
        netdevConfig = {
          Kind = "bridge";
          Name = proxyCfg.internalBridge;
        };
      };
      systemd.network.networks."20-${proxyCfg.internalBridge}" = {
        matchConfig.Name = proxyCfg.internalBridge;
        networkConfig = {
          LinkLocalAddressing = "no";
          IPv6AcceptRA = "no";
        };
        linkConfig.RequiredForOnline = "no";
      };
      networking.firewall.trustedInterfaces = [ proxyCfg.internalBridge ];
      boot.kernel.sysctl."net.ipv6.conf.${proxyCfg.internalBridge}.accept_ra" = 0;

      systemd.services."incus-create-${lxcName}" = {
        description = "Create Alpine LXC proxy container ${lxcName} if not exists";
        after = [ "incus-startup.service" "systemd-networkd.service" ];
        requires = [ "incus-startup.service" ];
        wantedBy = [ "multi-user.target" ];
        path = [ pkgs.incus pkgs.coreutils pkgs.gnugrep ];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
        };
        script = ''
          if incus info ${lxcName} &>/dev/null; then
            if incus config show ${lxcName} --expanded 2>/dev/null | grep -q 'parent: ${proxyCfg.internalBridge}'; then
              exit 0
            fi
            incus config device add ${lxcName} eth1 nic nictype=bridged parent=${proxyCfg.internalBridge} mtu=1400 2>/dev/null || true
            exit 0
          fi

          if ! incus remote list --format=csv | cut -d, -f1 | grep -qx "images"; then
            incus remote add images https://images.linuxcontainers.org \
              --protocol=simplestreams --public
          fi

          incus launch images:alpine/3.21 ${lxcName} \
            -c security.nesting=true \
            -d eth0,type=nic,nictype=bridged,parent=br-lan,mtu=1400 \
            -d eth1,type=nic,nictype=bridged,parent=${proxyCfg.internalBridge},mtu=1400
        '';
      };

      systemd.services."incus-setup-${lxcName}" = {
        description = "Setup tailscale and iptables in ${lxcName} LXC";
        after = [ "incus-create-${lxcName}.service" ];
        requires = [ "incus-create-${lxcName}.service" ];
        wantedBy = [ "multi-user.target" ];
        path = [ pkgs.incus pkgs.coreutils pkgs.gnugrep pkgs.gawk ];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          TimeoutStartSec = "120";
        };
        script = ''
          if incus exec ${lxcName} -- tailscale status --json 2>/dev/null | grep -q '"BackendState":"Running"'; then
            exit 0
          fi

          for i in $(seq 1 24); do
            STATUS=$(incus info ${lxcName} 2>/dev/null | awk '/^Status:/{print $2}')
            [ "$STATUS" = "RUNNING" ] && break
            sleep 5
          done
          if [ "$STATUS" != "RUNNING" ]; then
            echo "${lxcName} not RUNNING after 120s" >&2
            exit 1
          fi

          incus exec ${lxcName} -- apk update -q
          incus exec ${lxcName} -- apk add --no-cache tailscale iptables

          # eth1 static IP
          if ! incus exec ${lxcName} -- ip addr show eth1 2>/dev/null | grep -q '${proxyCfg.lxcIp}'; then
            incus exec ${lxcName} -- ip addr add ${proxyCfg.lxcIp}/24 dev eth1 2>/dev/null || true
            incus exec ${lxcName} -- ip link set eth1 up
          fi

          # IP forwarding
          incus exec ${lxcName} -- sysctl -w net.ipv4.ip_forward=1

          # iptables rules (idempotent)
          incus exec ${lxcName} -- sh -c 'iptables -t nat -C PREROUTING -i tailscale0 -j DNAT --to-destination ${proxyCfg.vmIp} 2>/dev/null || iptables -t nat -A PREROUTING -i tailscale0 -j DNAT --to-destination ${proxyCfg.vmIp}'
          ${lib.optionalString proxyCfg.enableLanForward ''
            incus exec ${lxcName} -- sh -c 'iptables -t nat -C PREROUTING -i eth0 -j DNAT --to-destination ${proxyCfg.vmIp} 2>/dev/null || iptables -t nat -A PREROUTING -i eth0 -j DNAT --to-destination ${proxyCfg.vmIp}'
          ''}
          incus exec ${lxcName} -- sh -c 'iptables -C FORWARD -d ${proxyCfg.vmIp} -j ACCEPT 2>/dev/null || iptables -A FORWARD -d ${proxyCfg.vmIp} -j ACCEPT'
          incus exec ${lxcName} -- sh -c 'iptables -C FORWARD -s ${proxyCfg.vmIp} -j ACCEPT 2>/dev/null || iptables -A FORWARD -s ${proxyCfg.vmIp} -j ACCEPT'
          incus exec ${lxcName} -- sh -c 'iptables -t nat -C POSTROUTING -s ${proxyCfg.internalSubnet} -o eth0 -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s ${proxyCfg.internalSubnet} -o eth0 -j MASQUERADE'

          # 재부팅 영속화 스크립트
          incus exec ${lxcName} -- mkdir -p /etc/local.d
          incus exec ${lxcName} -- sh -c 'echo "#!/bin/sh" > /etc/local.d/proxy.start'
          incus exec ${lxcName} -- sh -c 'echo "ip addr add ${proxyCfg.lxcIp}/24 dev eth1 2>/dev/null || true" >> /etc/local.d/proxy.start'
          incus exec ${lxcName} -- sh -c 'echo "ip link set eth1 up" >> /etc/local.d/proxy.start'
          incus exec ${lxcName} -- sh -c 'echo "sysctl -w net.ipv4.ip_forward=1" >> /etc/local.d/proxy.start'
          incus exec ${lxcName} -- sh -c 'echo "iptables -t nat -A PREROUTING -i tailscale0 -j DNAT --to-destination ${proxyCfg.vmIp} 2>/dev/null || true" >> /etc/local.d/proxy.start'
          ${lib.optionalString proxyCfg.enableLanForward ''
            incus exec ${lxcName} -- sh -c 'echo "iptables -t nat -A PREROUTING -i eth0 -j DNAT --to-destination ${proxyCfg.vmIp} 2>/dev/null || true" >> /etc/local.d/proxy.start'
          ''}
          incus exec ${lxcName} -- sh -c 'echo "iptables -A FORWARD -d ${proxyCfg.vmIp} -j ACCEPT 2>/dev/null || true" >> /etc/local.d/proxy.start'
          incus exec ${lxcName} -- sh -c 'echo "iptables -A FORWARD -s ${proxyCfg.vmIp} -j ACCEPT 2>/dev/null || true" >> /etc/local.d/proxy.start'
          incus exec ${lxcName} -- sh -c 'echo "iptables -t nat -A POSTROUTING -s ${proxyCfg.internalSubnet} -o eth0 -j MASQUERADE 2>/dev/null || true" >> /etc/local.d/proxy.start'
          incus exec ${lxcName} -- chmod +x /etc/local.d/proxy.start
          incus exec ${lxcName} -- rc-update add local default

          # tailscale 활성화
          incus exec ${lxcName} -- rc-update add tailscale default
          incus exec ${lxcName} -- rc-service tailscale start

          if [ -f "${proxyCfg.preauthKeyFile}" ]; then
            PREAUTH_KEY=$(cat "${proxyCfg.preauthKeyFile}")
            incus exec ${lxcName} -- tailscale up \
              --authkey="$PREAUTH_KEY" \
              --login-server="${proxyCfg.loginServer}" \
              --accept-routes
          else
            echo "WARNING: preauthKeyFile not found at ${proxyCfg.preauthKeyFile}" >&2
          fi
        '';
      };

      systemd.services."incus-update-vm-nic-${name}" = {
        description = "Move ${proxyCfg.vmName} NIC from br-lan to ${proxyCfg.internalBridge}";
        after = [ "incus-create-${lxcName}.service" "systemd-networkd.service" ];
        requires = [ "incus-create-${lxcName}.service" ];
        wantedBy = [ "multi-user.target" ];
        path = [ pkgs.incus pkgs.coreutils pkgs.gnugrep pkgs.gawk pkgs.findutils ];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          TimeoutStartSec = "300";
        };
        script = ''
          if incus config show ${proxyCfg.vmName} --expanded 2>/dev/null | grep -q 'parent: ${proxyCfg.internalBridge}'; then
            exit 0
          fi

          if ! incus info ${proxyCfg.vmName} &>/dev/null; then
            echo "VM ${proxyCfg.vmName} not found, skipping NIC update" >&2
            exit 1
          fi

          STATUS=$(incus info ${proxyCfg.vmName} 2>/dev/null | awk '/^Status:/{print $2}')
          if [ "$STATUS" = "RUNNING" ]; then
            incus stop ${proxyCfg.vmName} --force
            for i in $(seq 1 12); do
              STATUS=$(incus info ${proxyCfg.vmName} 2>/dev/null | awk '/^Status:/{print $2}')
              [ "$STATUS" = "STOPPED" ] && break
              sleep 5
            done
          fi

          incus config device remove ${proxyCfg.vmName} eth0 2>/dev/null || true
          incus config device add ${proxyCfg.vmName} eth0 nic \
            nictype=bridged parent=${proxyCfg.internalBridge} mtu=1400

          incus start ${proxyCfg.vmName}

          for i in $(seq 1 36); do
            incus exec ${proxyCfg.vmName} -- true 2>/dev/null && break
            sleep 5
          done

          if ! incus exec ${proxyCfg.vmName} -- true 2>/dev/null; then
            echo "VM ${proxyCfg.vmName} agent not reachable after 180s" >&2
            exit 1
          fi

          NETPLAN_TMP=$(mktemp)
          cat > "$NETPLAN_TMP" << 'NETPLAN'
network:
  version: 2
  ethernets:
    internal:
      match:
        name: 'en*'
      set-name: eth0
      addresses:
        - ${proxyCfg.vmIp}/24
      routes:
        - to: default
          via: ${proxyCfg.lxcIp}
      nameservers:
        addresses: [1.1.1.1, 8.8.8.8]
NETPLAN
          incus file push "$NETPLAN_TMP" ${proxyCfg.vmName}/etc/netplan/50-incus-static.yaml --uid 0 --gid 0 --mode 0600
          rm "$NETPLAN_TMP"

          incus exec ${proxyCfg.vmName} -- find /etc/netplan -name "*.yaml" -not -name "50-incus-static.yaml" -delete
          incus exec ${proxyCfg.vmName} -- netplan apply
        '';
      };
    };
in {
  options.mods.sys.services."incus-tailscale-proxy" = {
    enable = lib.mkEnableOption "Incus Tailscale Proxy — LXC-based tailscale ingress for Incus VMs";
    proxies = lib.mkOption {
      type = lib.types.attrsOf (lib.types.submodule {
        options = {
          vmName = lib.mkOption {
            type = lib.types.str;
            description = "Incus VM name to proxy";
          };
          internalBridge = lib.mkOption {
            type = lib.types.str;
            description = "Internal bridge name (e.g. incusbr-devserver)";
          };
          lxcIp = lib.mkOption {
            type = lib.types.str;
            description = "LXC static IP on internal bridge (gateway for VM)";
          };
          vmIp = lib.mkOption {
            type = lib.types.str;
            description = "VM static IP on internal bridge";
          };
          internalSubnet = lib.mkOption {
            type = lib.types.str;
            description = "Internal subnet CIDR (e.g. 10.0.1.0/24)";
          };
          preauthKeyFile = lib.mkOption {
            type = lib.types.str;
            description = "Host path to tailscale preauth key file";
          };
          loginServer = lib.mkOption {
            type = lib.types.str;
            description = "Headscale server URL";
          };
          enableLanForward = lib.mkOption {
            type = lib.types.bool;
            default = true;
            description = "Also DNAT from eth0 (br-lan) to vmIp";
          };
        };
      });
      default = {};
      description = "Attribute set of proxy configs, keyed by proxy name";
    };
  };

  config = lib.mkIf cfg.enable (
    lib.mkMerge (lib.mapAttrsToList mkProxyConfig cfg.proxies)
  );
}
