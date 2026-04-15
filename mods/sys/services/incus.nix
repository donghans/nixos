{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services.incus;

  # 1. autounattend.xml 내용 정의
  unattendXml = pkgs.writeText "autounattend.xml" ''
    <?xml version="1.0" encoding="utf-8"?>
    <unattend xmlns="urn:schemas-microsoft-com:unattend">
        <settings pass="windowsPE">
            <component name="Microsoft-Windows-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
                <UserData><AcceptEula>true</AcceptEula></UserData>
                <RunSynchronous>
                    <RunSynchronousCommand wcm:action="add">
                        <Order>1</Order>
                        <Path>reg add HKLM\System\Setup\LabConfig /v BypassTPMCheck /t REG_DWORD /d 1 /f</Path>
                    </RunSynchronousCommand>
                    <RunSynchronousCommand wcm:action="add">
                        <Order>2</Order>
                        <Path>reg add HKLM\System\Setup\LabConfig /v BypassRAMCheck /t REG_DWORD /d 1 /f</Path>
                    </RunSynchronousCommand>
                </RunSynchronous>
            </component>
        </settings>
        <settings pass="oobeSystem">
            <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS">
                <OOBE>
                    <HideEULAPage>true</HideEULAPage>
                    <HideLocalAccountScreen>true</HideLocalAccountScreen>
                    <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
                    <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
                    <NetworkLocation>Work</NetworkLocation>
                    <ProtectYourPC>3</ProtectYourPC>
                </OOBE>
                <UserAccounts>
                    <LocalAccounts>
                        <LocalAccount wcm:action="add">
                            <Password><Value></Value><PlainText>true</PlainText></Password>
                            <DisplayName>${config.workspace.username}</DisplayName>
                            <Group>Administrators</Group>
                            <Name>${config.workspace.username}</Name>
                        </LocalAccount>
                    </LocalAccounts>
                </UserAccounts>
                <AutoLogon>
                    <Password><Value></Value><PlainText>true</PlainText></Password>
                    <Enabled>true</Enabled>
                    <Username>${config.workspace.username}</Username>
                </AutoLogon>
            </component>
        </settings>
    </unattend>
  '';

  # 2. XML을 포함한 가상 ISO 빌드
  unattendIso = pkgs.runCommand "win11-unattend.iso" {nativeBuildInputs = [pkgs.cdrkit];} ''
    mkdir -p iso
    cp ${unattendXml} iso/autounattend.xml
    genisoimage -output $out -volid "OEM" -J -r iso
  '';
in {
  options.mods.sys.services.incus.enable = mkEnableOption "Incus hypervisor";

  config = mkIf cfg.enable (
    if isNixOS
    then {
      virtualisation.incus.enable = true;
      virtualisation.incus.ui.enable = true;
      networking.firewall.allowedTCPPorts = [8443];
      networking.nftables.enable = true;
      users.users.${config.workspace.username}.extraGroups = ["incus-admin"];

      virtualisation.incus.preseed = {
        networks = [
          {
            name = "incusbr0";
            type = "bridge";
            config = {
              "ipv4.address" = "auto";
              "ipv6.address" = "auto";
              "ipv4.nat" = "true";
              "ipv6.nat" = "true";
            };
          }
        ];
        storage_pools = [
          {
            name = "default";
            driver = "btrfs";
            config = {
              source = "/var/lib/incus/storage-pools/default";
            };
          }
        ];
        profiles = [
          {
            name = "default";
            devices = {
              eth0 = {
                name = "eth0";
                network = "incusbr0";
                type = "nic";
              };
              root = {
                path = "/";
                pool = "default";
                type = "disk";
              };
            };
          }
          {
            name = "win11";
            config = {
              "limits.cpu" = "4";
              "limits.memory" = "8GiB";
              "raw.qemu" = "-device usb-tablet";
              "security.secureboot" = "true";
            };
            devices = {
              eth0 = {
                name = "eth0";
                network = "incusbr0";
                type = "nic";
              };
              root = {
                path = "/";
                pool = "default";
                type = "disk";
                "io.bus" = "nvme";
                size = "64GiB";
              };
              # 3. 빌드된 ISO를 win11 프로필에 자동 연결
              unattend-iso = {
                source = "${unattendIso}";
                type = "disk";
                "io.bus" = "usb";
              };
              vtpm = {
                type = "tpm";
              };
            };
          }
        ];
      };
    }
    else {}
  );
}
