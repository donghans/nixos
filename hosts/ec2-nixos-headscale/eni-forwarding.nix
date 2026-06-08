{lib, ...}:
(import ../_lib/ip-forwarder.nix {inherit lib;}) {
  interface = "eth1";
  gateway = "172.31.48.1";
  subnetPrefix = 20;
  dhcp = true; # eth1은 secondary NIC — DHCP로 primary IP 수령
  forwards = [
    # eth1 primary IP (DHCP 할당) → Mac Studio
    {
      publicIp = "172.31.60.101";
      targetTs = "100.64.0.5";
      staticAssign = false;
    }
    # eth1 secondary IP (정적) → Incus VM (ubuntu-2404)
    {
      publicIp = "172.31.51.159";
      targetTs = "100.64.0.12";
      staticAssign = true;
    }
  ];
}
