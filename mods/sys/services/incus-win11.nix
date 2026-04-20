{mkMod, ...}:
mkMod __curPos "Incus win11 profile" ({
  cfg,
  config,
  pkgs,
  lib,
  ...
}: let
  # 첫 로그인 시 실행되는 디블로팅 스크립트
  # - 불필요한 AppX 패키지 제거
  # - 불필요 서비스 비활성화
  # - 절전·화면꺼짐 비활성화
  # - 텔레메트리 비활성화
  debloatScript = pkgs.writeText "debloat.ps1" ''
    # AppX 패키지 제거
    $remove = @(
      "Microsoft.Xbox*",
      "Microsoft.GamingApp",
      "Microsoft.XboxGameOverlay",
      "Microsoft.XboxGamingOverlay",
      "Microsoft.XboxIdentityProvider",
      "Microsoft.XboxSpeechToTextOverlay",
      "Microsoft.MicrosoftSolitaireCollection",
      "Microsoft.ZuneMusic",
      "Microsoft.ZuneVideo",
      "Microsoft.WindowsMaps",
      "Microsoft.BingWeather",
      "Microsoft.BingNews",
      "Microsoft.People",
      "Microsoft.SkypeApp",
      "Microsoft.Teams",
      "MicrosoftTeams",
      "Microsoft.MicrosoftOfficeHub",
      "Microsoft.WindowsFeedbackHub",
      "Microsoft.GetHelp",
      "Microsoft.Getstarted",
      "Microsoft.YourPhone",
      "Clipchamp.Clipchamp",
      "Microsoft.WindowsCommunicationsApps",
      "Microsoft.OutlookForWindows"
    )
    foreach ($app in $remove) {
      Get-AppxPackage -Name $app -AllUsers -ErrorAction SilentlyContinue |
        Remove-AppxPackage -AllUsers -ErrorAction SilentlyContinue
      Get-AppxProvisionedPackage -Online -ErrorAction SilentlyContinue |
        Where-Object DisplayName -like $app |
        Remove-AppxProvisionedPackage -Online -ErrorAction SilentlyContinue
    }

    # 서비스 비활성화
    $svcs = @(
      "SysMain",          # Superfetch
      "WSearch",          # Windows Search 인덱싱
      "Spooler",          # 프린터 스풀러
      "Fax",
      "DiagTrack",        # 원격 측정
      "dmwappushservice", # 원격 측정
      "lfsvc",            # 위치
      "MapsBroker",
      "WbioSrvc",         # 생체인식
      "WerSvc",           # 오류 보고
      "XblAuthManager", "XblGameSave", "XboxNetApiSvc", "XboxGipSvc",
      "DoSvc",            # 배달 최적화
      "icssvc",           # 모바일 핫스팟
      "wisvc"             # Windows Insider
    )
    foreach ($s in $svcs) {
      Set-Service -Name $s -StartupType Disabled -ErrorAction SilentlyContinue
      Stop-Service -Name $s -Force -ErrorAction SilentlyContinue
    }

    # 절전·화면꺼짐·하드디스크 자동끄기 비활성화 (호스트 OS에서 절전 관리)
    powercfg /change standby-timeout-ac 0
    powercfg /change standby-timeout-dc 0
    powercfg /change hibernate-timeout-ac 0
    powercfg /change hibernate-timeout-dc 0
    powercfg /change monitor-timeout-ac 0
    powercfg /change monitor-timeout-dc 0
    powercfg /change disk-timeout-ac 0
    powercfg /change disk-timeout-dc 0
    powercfg /h off

    # 텔레메트리 비활성화
    reg add "HKLM\SOFTWARE\Policies\Microsoft\Windows\DataCollection" /v AllowTelemetry /t REG_DWORD /d 0 /f

    # 작업표시줄 위젯·채팅 제거
    reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced" /v TaskbarDa /t REG_DWORD /d 0 /f
    reg add "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced" /v TaskbarMn /t REG_DWORD /d 0 /f

    # Windows Update 수동으로 변경
    Set-Service -Name wuauserv -StartupType Manual -ErrorAction SilentlyContinue
  '';

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
                <FirstLogonCommands>
                    <!-- 1. debloat.ps1을 C:\로 복사 (USB 드라이브 문자가 유동적이므로 탐색) -->
                    <SynchronousCommand wcm:action="add">
                        <Order>1</Order>
                        <CommandLine>cmd /c for %d in (D E F G H) do if exist %d:\debloat.ps1 copy /Y %d:\debloat.ps1 C:\debloat.ps1</CommandLine>
                        <RequiresUserInput>false</RequiresUserInput>
                    </SynchronousCommand>
                    <!-- 2. virtio-win guest tools 설치 (QXL 디스플레이, SPICE 에이전트, netkvm 네트워크) -->
                    <SynchronousCommand wcm:action="add">
                        <Order>2</Order>
                        <CommandLine>cmd /c for %d in (D E F G H) do if exist %d:\virtio-win-guest-tools.exe %d:\virtio-win-guest-tools.exe /S /norestart</CommandLine>
                        <RequiresUserInput>false</RequiresUserInput>
                    </SynchronousCommand>
                    <!-- 3. 디블로팅: 불필요 앱 제거, 서비스 비활성화, 절전 끄기 -->
                    <SynchronousCommand wcm:action="add">
                        <Order>3</Order>
                        <CommandLine>powershell -ExecutionPolicy Bypass -NonInteractive -File C:\debloat.ps1</CommandLine>
                        <RequiresUserInput>false</RequiresUserInput>
                    </SynchronousCommand>
                </FirstLogonCommands>
            </component>
        </settings>
    </unattend>
  '';

  setupIso = pkgs.runCommand "win11-setup.iso" {nativeBuildInputs = [pkgs.cdrkit];} ''
    mkdir -p iso/vioscsi/w11/amd64
    cp ${unattendXml} iso/autounattend.xml
    cp ${debloatScript} iso/debloat.ps1
    # vioscsi: Windows PE에서 가상 디스크 인식용
    cp ${pkgs.virtio-win}/vioscsi/w11/amd64/vioscsi.inf iso/vioscsi/w11/amd64/
    cp ${pkgs.virtio-win}/vioscsi/w11/amd64/vioscsi.sys iso/vioscsi/w11/amd64/
    cp ${pkgs.virtio-win}/vioscsi/w11/amd64/vioscsi.cat iso/vioscsi/w11/amd64/
    # virtio-win-guest-tools: FirstLogonCommands에서 설치 (QXL, SPICE 에이전트, netkvm 등 일괄)
    cp ${pkgs.virtio-win}/virtio-win-guest-tools.exe iso/
    genisoimage -output $out -volid "SETUP" -J -joliet-long iso
  '';
in {
  os = {
    assertions = [
      {
        assertion = config.mods.sys.services.incus.enable;
        message = "mods.sys.services.incus-win11는 mods.sys.services.incus.enable = true 가 필요합니다";
      }
    ];
    virtualisation.incus.preseed.profiles = [
      {
        name = "win11";
        config = {
          "limits.cpu" = "4";
          "limits.memory" = "8GiB";
          # SPICE 동적 해상도는 virtio-win-guest-tools의 SPICE VDAgent가 처리
          # (Incus가 qemu.conf에서 디스플레이 장치를 자체 설정하므로 qxl-vga 직접 추가 불필요)
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
  };
})
