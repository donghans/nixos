# Incus Tailscale Proxy — LXC 기반 tailscale 인그레스 헬퍼
# 이 파일은 NixOS 모듈이 아닌 순수 Nix 함수다 (underscore prefix → auto-import 제외).
# 사용법: mkHostConfiguration에서 os.imports에 결과를 삽입.
#
# 예:
#   let mkTailscaleProxy = import ./_lib/incus-tailscale-proxy.nix {inherit lib pkgs;};
#   in mkHostConfiguration (_: {
#     os.imports = [(mkTailscaleProxy "devserver" { vmName = "ubuntu-2404"; ... })];
#   })
#
# internalBridge = null → LAN target 모드 (물리 머신 대상, eth1/내부 bridge 불필요)
{
  lib,
  pkgs,
}: name: {
  vmName,
  internalBridge ? null,
  lxcIp ? null,
  vmIp,
  internalSubnet ? null,
  stateFile,
  enableLanForward ? true,
}: let
  lxcName = "${name}-proxy";
  # internal bridge 없으면 vmIp/32를 masquerade 대상으로 사용
  masqueradeSubnet = if internalSubnet != null then internalSubnet else "${vmIp}/32";
in {
  config = lib.mkMerge [
    {
      systemd.services."incus-create-${lxcName}" = {
        description = "Create Alpine LXC proxy container ${lxcName} if not exists";
        after = ["incus-startup.service" "systemd-networkd.service"];
        requires = ["incus-startup.service"];
        wantedBy = ["multi-user.target"];
        path = [pkgs.incus pkgs.coreutils pkgs.gnugrep];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
        };
        script = ''
          if incus info ${lxcName} &>/dev/null; then
            ${lib.optionalString (internalBridge != null) ''
              if incus config show ${lxcName} --expanded 2>/dev/null | grep -q 'parent: ${internalBridge}'; then
                # LXC NIC은 모두 macvlan을 사용해야 함 (incus 6.x가 unmanaged bridge에 veth를 붙이지 않음)
                # eth0 또는 eth1 중 nictype=bridged인 것이 있으면 macvlan으로 교체
                NEED_FIX=0
                incus config show ${lxcName} --expanded 2>/dev/null | grep -q 'nictype: bridged' && NEED_FIX=1
                if [ "$NEED_FIX" = "1" ]; then
                  incus stop ${lxcName} --force 2>/dev/null || true
                  incus config device remove ${lxcName} eth0 2>/dev/null || true
                  incus config device remove ${lxcName} eth1 2>/dev/null || true
                  incus config device add ${lxcName} eth0 nic nictype=macvlan parent=br-lan mtu=1400
                  incus config device add ${lxcName} eth1 nic nictype=macvlan parent=${internalBridge} mtu=1400
                  incus start ${lxcName}
                fi
                exit 0
              fi
              incus config device add ${lxcName} eth1 nic nictype=macvlan parent=${internalBridge} mtu=1400 2>/dev/null || true
            ''}
            exit 0
          fi

          if ! incus remote list --format=csv | cut -d, -f1 | grep -qx "images"; then
            incus remote add images https://images.linuxcontainers.org \
              --protocol=simplestreams --public
          fi

          incus launch images:alpine/3.21 ${lxcName} -c security.nesting=true

          # 컨테이너가 초기화되는 동안 잠깐 대기
          sleep 2
          incus stop ${lxcName} --force 2>/dev/null || true

          # 기본 프로필의 eth0(incusbr0) 제거 후 br-lan macvlan으로 교체
          # incus 6.x는 unmanaged bridge에 veth를 붙이지 않음 → LXC NIC은 모두 macvlan 사용
          incus config device remove ${lxcName} eth0 2>/dev/null || true
          incus config device add ${lxcName} eth0 nic nictype=macvlan parent=br-lan mtu=1400

          ${lib.optionalString (internalBridge != null) ''
            # internal bridge용 eth1 (macvlan: 같은 이유로 bridged 대신)
            incus config device add ${lxcName} eth1 nic nictype=macvlan parent=${internalBridge} mtu=1400
          ''}

          incus start ${lxcName}
        '';
      };

      systemd.services."incus-setup-${lxcName}" = {
        description = "Setup tailscale and iptables in ${lxcName} LXC";
        after = ["incus-create-${lxcName}.service"];
        requires = ["incus-create-${lxcName}.service"];
        wantedBy = ["multi-user.target"];
        path = [pkgs.incus pkgs.coreutils pkgs.gnugrep pkgs.gawk];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          TimeoutStartSec = "120";
        };
        script = ''
          if incus exec ${lxcName} -- tailscale status --json 2>/dev/null | grep -q '"BackendState":"Running"'; then
            incus exec ${lxcName} -- tailscale set --hostname="${vmName}" 2>/dev/null || true
            exit 0
          fi

          for i in $(seq 1 24); do
            incus exec ${lxcName} -- true 2>/dev/null && break
            sleep 5
          done
          if ! incus exec ${lxcName} -- true 2>/dev/null; then
            echo "${lxcName} exec not ready after 120s" >&2
            exit 1
          fi

          # eth0 DHCP IP 대기 (macvlan은 빠르나 안전 마진)
          for i in $(seq 1 12); do
            incus exec ${lxcName} -- ip addr show eth0 2>/dev/null | grep -q 'inet ' && break
            sleep 5
          done
          if ! incus exec ${lxcName} -- ip addr show eth0 2>/dev/null | grep -q 'inet '; then
            echo "${lxcName} eth0 no IPv4 after 60s" >&2
            exit 1
          fi

          incus exec ${lxcName} -- apk update -q
          incus exec ${lxcName} -- apk add --no-cache tailscale iptables

          ${lib.optionalString (internalBridge != null) ''
            # eth1 static IP
            if ! incus exec ${lxcName} -- ip addr show eth1 2>/dev/null | grep -q '${lxcIp}'; then
              incus exec ${lxcName} -- ip addr add ${lxcIp}/24 dev eth1 2>/dev/null || true
              incus exec ${lxcName} -- ip link set eth1 up
            fi
          ''}

          # IP forwarding
          incus exec ${lxcName} -- sysctl -w net.ipv4.ip_forward=1

          # iptables rules (idempotent)
          incus exec ${lxcName} -- sh -c 'iptables -t nat -C PREROUTING -i tailscale0 -j DNAT --to-destination ${vmIp} 2>/dev/null || iptables -t nat -A PREROUTING -i tailscale0 -j DNAT --to-destination ${vmIp}'
          ${lib.optionalString enableLanForward ''
            incus exec ${lxcName} -- sh -c 'iptables -t nat -C PREROUTING -i eth0 -j DNAT --to-destination ${vmIp} 2>/dev/null || iptables -t nat -A PREROUTING -i eth0 -j DNAT --to-destination ${vmIp}'
          ''}
          incus exec ${lxcName} -- sh -c 'iptables -C FORWARD -d ${vmIp} -j ACCEPT 2>/dev/null || iptables -A FORWARD -d ${vmIp} -j ACCEPT'
          incus exec ${lxcName} -- sh -c 'iptables -C FORWARD -s ${vmIp} -j ACCEPT 2>/dev/null || iptables -A FORWARD -s ${vmIp} -j ACCEPT'
          incus exec ${lxcName} -- sh -c 'iptables -t nat -C POSTROUTING -s ${masqueradeSubnet} -o eth0 -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -s ${masqueradeSubnet} -o eth0 -j MASQUERADE'

          # 재부팅 영속화 스크립트
          incus exec ${lxcName} -- mkdir -p /etc/local.d
          incus exec ${lxcName} -- sh -c 'echo "#!/bin/sh" > /etc/local.d/proxy.start'
          ${lib.optionalString (internalBridge != null) ''
            incus exec ${lxcName} -- sh -c 'echo "ip addr add ${lxcIp}/24 dev eth1 2>/dev/null || true" >> /etc/local.d/proxy.start'
            incus exec ${lxcName} -- sh -c 'echo "ip link set eth1 up" >> /etc/local.d/proxy.start'
          ''}
          incus exec ${lxcName} -- sh -c 'echo "sysctl -w net.ipv4.ip_forward=1" >> /etc/local.d/proxy.start'
          incus exec ${lxcName} -- sh -c 'echo "iptables -t nat -A PREROUTING -i tailscale0 -j DNAT --to-destination ${vmIp} 2>/dev/null || true" >> /etc/local.d/proxy.start'
          ${lib.optionalString enableLanForward ''
            incus exec ${lxcName} -- sh -c 'echo "iptables -t nat -A PREROUTING -i eth0 -j DNAT --to-destination ${vmIp} 2>/dev/null || true" >> /etc/local.d/proxy.start'
          ''}
          incus exec ${lxcName} -- sh -c 'echo "iptables -A FORWARD -d ${vmIp} -j ACCEPT 2>/dev/null || true" >> /etc/local.d/proxy.start'
          incus exec ${lxcName} -- sh -c 'echo "iptables -A FORWARD -s ${vmIp} -j ACCEPT 2>/dev/null || true" >> /etc/local.d/proxy.start'
          incus exec ${lxcName} -- sh -c 'echo "iptables -t nat -A POSTROUTING -s ${masqueradeSubnet} -o eth0 -j MASQUERADE 2>/dev/null || true" >> /etc/local.d/proxy.start'
          incus exec ${lxcName} -- chmod +x /etc/local.d/proxy.start
          incus exec ${lxcName} -- rc-update add local default

          # tailscale 활성화
          incus exec ${lxcName} -- rc-update add tailscale default

          if [ -f "${stateFile}" ]; then
            incus exec ${lxcName} -- mkdir -p /var/lib/tailscale
            incus file push "${stateFile}" ${lxcName}/var/lib/tailscale/tailscaled.state \
              --uid 0 --gid 0 --mode 0600
            incus exec ${lxcName} -- rc-service tailscale start
            incus exec ${lxcName} -- tailscale set --hostname="${vmName}"
          else
            echo "WARNING: stateFile not found at ${stateFile}" >&2
            incus exec ${lxcName} -- rc-service tailscale start
          fi
        '';
      };
    }

    (lib.mkIf (internalBridge != null) {
      systemd.network.netdevs."10-${internalBridge}" = {
        netdevConfig = {
          Kind = "bridge";
          Name = internalBridge;
        };
      };
      systemd.network.networks."20-${internalBridge}" = {
        matchConfig.Name = internalBridge;
        networkConfig = {
          LinkLocalAddressing = "no";
          IPv6AcceptRA = "no";
        };
        linkConfig.RequiredForOnline = "no";
      };
      networking.firewall.trustedInterfaces = [internalBridge];
      boot.kernel.sysctl."net.ipv6.conf.${internalBridge}.accept_ra" = 0;

      systemd.services."incus-update-vm-nic-${name}" = {
        description = "Move ${vmName} NIC from br-lan to ${internalBridge}";
        after = ["incus-create-${lxcName}.service" "systemd-networkd.service"];
        requires = ["incus-create-${lxcName}.service"];
        wantedBy = ["multi-user.target"];
        path = [pkgs.incus pkgs.coreutils pkgs.gnugrep pkgs.gawk pkgs.findutils];
        serviceConfig = {
          Type = "oneshot";
          RemainAfterExit = true;
          TimeoutStartSec = "300";
        };
        script = ''
                  if incus config show ${vmName} --expanded 2>/dev/null | grep -q 'parent: ${internalBridge}'; then
                    exit 0
                  fi

                  if ! incus info ${vmName} &>/dev/null; then
                    echo "VM ${vmName} not found, skipping NIC update" >&2
                    exit 1
                  fi

                  STATUS=$(incus info ${vmName} 2>/dev/null | awk '/^Status:/{print $2}')
                  if [ "$STATUS" = "RUNNING" ]; then
                    incus stop ${vmName} --force
                    for i in $(seq 1 12); do
                      STATUS=$(incus info ${vmName} 2>/dev/null | awk '/^Status:/{print $2}')
                      [ "$STATUS" = "STOPPED" ] && break
                      sleep 5
                    done
                  fi

                  incus config device remove ${vmName} eth0 2>/dev/null || true
                  incus config device add ${vmName} eth0 nic \
                    nictype=bridged parent=${internalBridge} mtu=1400

                  incus start ${vmName}

                  for i in $(seq 1 36); do
                    incus exec ${vmName} -- true 2>/dev/null && break
                    sleep 5
                  done

                  if ! incus exec ${vmName} -- true 2>/dev/null; then
                    echo "VM ${vmName} agent not reachable after 180s" >&2
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
                  - ${vmIp}/24
                routes:
                  - to: default
                    via: ${lxcIp}
                nameservers:
                  addresses: [1.1.1.1, 8.8.8.8]
          NETPLAN
                  incus file push "$NETPLAN_TMP" ${vmName}/etc/netplan/50-incus-static.yaml --uid 0 --gid 0 --mode 0600
                  rm "$NETPLAN_TMP"

                  incus exec ${vmName} -- find /etc/netplan -name "*.yaml" -not -name "50-incus-static.yaml" -delete
                  incus exec ${vmName} -- netplan apply
        '';
      };
    })
  ];
}
