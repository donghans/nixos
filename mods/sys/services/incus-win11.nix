{mkMod, ...}:
mkMod __curPos "Incus win11 profile" ({
  config,
  pkgs,
  ...
}: let
  # 첫 로그인 시 실행되는 디블로팅 스크립트 (mods/_data/incus/win11.debloat.ps1)
  debloatScript =
    pkgs.writeText "debloat.ps1"
    (builtins.readFile ../../_data/incus/win11.debloat.ps1);

  # autounattend.xml + vioscsi 드라이버를 하나의 ISO에 통합 (mods/_data/incus/win11.autounattend.xml)
  # → 드라이브가 하나만 추가되어 문자 밀림 현상 없음
  #
  # 주의: preseed는 장치를 추가/업데이트만 함. 장치 이름을 변경하면
  # 구 이름이 프로필에 잔존하므로 nixup os 후 incus profile show win11 로 확인 필요.
  unattendXml =
    pkgs.writeText "autounattend.xml"
    (builtins.readFile ../../_data/incus/win11.autounattend.xml);

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
