{
  config,
  lib,
  pkgs,
  isNixOS ? false,
  ...
}:
with lib; let
  cfg = config.mods.sys.services."incus-win11";

  # autounattend.xml + vioscsi 드라이버를 하나의 ISO에 통합
  # → 드라이브가 하나만 추가되어 문자 밀림 현상 없음
  #
  # 주의: preseed는 장치를 추가/업데이트만 함. 장치 이름을 변경하면
  # 구 이름이 프로필에 잔존하므로 nixup os 후 incus profile show win11 로 확인 필요.
  unattendXml = pkgs.writeText "autounattend.xml" ''
    <?xml version="1.0" encoding="utf-8"?>
    <unattend xmlns="urn:schemas-microsoft-com:unattend">
        <settings pass="windowsPE">
            <component name="Microsoft-Windows-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
                <RunSynchronous>
                    <!-- 드라이브 문자가 고정되지 않으므로 C~H 순으로 vioscsi.inf를 탐색해 로드 -->
                    <RunSynchronousCommand wcm:action="add">
                        <Order>1</Order>
                        <Path>cmd /c (for %d in (C D E F G H) do if exist %d:\vioscsi\w11\amd64\vioscsi.inf drvload %d:\vioscsi\w11\amd64\vioscsi.inf) &amp; exit 0</Path>
                        <WillReboot>Never</WillReboot>
                    </RunSynchronousCommand>
                </RunSynchronous>
                <UserData><AcceptEula>true</AcceptEula></UserData>
            </component>
        </settings>
        <settings pass="offlineServicing">
            <component name="Microsoft-Windows-PnpCustomizationsNonWinPE" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
                <DriverPaths>
                    <!-- offlineServicing는 파일 복사 후·첫 부팅 전에 실행 → PE에서 접근 가능한 경로로 vioscsi를 이미지에 영구 주입 -->
                    <PathAndCredentials wcm:action="add" wcm:keyValue="1"><Path>D:\vioscsi\w11\amd64</Path></PathAndCredentials>
                    <PathAndCredentials wcm:action="add" wcm:keyValue="2"><Path>E:\vioscsi\w11\amd64</Path></PathAndCredentials>
                    <PathAndCredentials wcm:action="add" wcm:keyValue="3"><Path>F:\vioscsi\w11\amd64</Path></PathAndCredentials>
                </DriverPaths>
            </component>
        </settings>
        <settings pass="oobeSystem">
            <component name="Microsoft-Windows-Shell-Setup" processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
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
                            <DisplayName>PC</DisplayName>
                            <Group>Administrators</Group>
                            <Name>PC</Name>
                        </LocalAccount>
                    </LocalAccounts>
                </UserAccounts>
                <AutoLogon>
                    <Password><Value></Value><PlainText>true</PlainText></Password>
                    <Enabled>true</Enabled>
                    <Username>PC</Username>
                </AutoLogon>
            </component>
        </settings>
    </unattend>
  '';

  setupIso = pkgs.runCommand "win11-setup.iso" {nativeBuildInputs = [pkgs.cdrkit];} ''
    mkdir -p iso/vioscsi/w11/amd64
    cp ${unattendXml} iso/autounattend.xml
    cp ${pkgs.virtio-win}/vioscsi/w11/amd64/vioscsi.inf iso/vioscsi/w11/amd64/
    cp ${pkgs.virtio-win}/vioscsi/w11/amd64/vioscsi.sys iso/vioscsi/w11/amd64/
    cp ${pkgs.virtio-win}/vioscsi/w11/amd64/vioscsi.cat iso/vioscsi/w11/amd64/
    genisoimage -output $out -volid "SETUP" -J -joliet-long iso
  '';
in {
  options.mods.sys.services."incus-win11".enable = mkEnableOption "Incus win11 profile";

  config = mkIf cfg.enable (
    if isNixOS
    then {
      virtualisation.incus.preseed.profiles = [
        {
          name = "win11";
          config = {
            "limits.cpu" = "4";
            "limits.memory" = "8GiB";
            "raw.qemu" = "-device usb-tablet -boot menu=on,splash-time=5000";
            "security.secureboot" = "false";
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
              "io.bus" = "virtio-scsi";
              size = "64GiB";
            };
            setup = {
              source = "${setupIso}";
              type = "disk";
              "io.bus" = "usb";
            };
            vtpm = {
              type = "tpm";
            };
          };
        }
      ];
    }
    else {}
  );
}
