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
