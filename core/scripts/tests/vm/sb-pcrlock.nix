# Secure Boot + lanzaboote UKI + swtpm 위에서 「TPM2+PIN(pcrlock) 으로 LUKS 를 푸는」 흐름을 재현하는 NixOS VM 시험.
# 쓰는 곳: S6(TPM+PIN) 의 설계 근거 시험, 이후 nixseal tpm / recover 의 VM 시험 틀. 실행은 ./default.nix 의 주석 참고.
#
# 시나리오(scenario):
#   positive … A(등록 직후 PIN 으로 열림) → C(dbx 를 바꾸고 「재부팅 전에」 정책 갱신 → PIN 으로 열림)
#   negative … A → B(dbx 만 바꾸고 갱신 안 함 → TPM 이 거부) → D1(그 상태에선 정책 갱신도 거부됨)
#              → D2(remove-policy + 복구 암호로 재등록 → PIN 으로 열림)
#
# 이 틀이 제대로 돌려면 필요한 것(시행착오로 확인 — 빠뜨리면 조용히 실패한다; 해당 설정은 core/lib/luks-tpm2.nix 에 있고 luks mod 와 공유):
#   - lanzaboote 스텁이 ESP 의 \loader\credentials\pcrlock.*.cred 를 initrd 로 넘긴다. 그 파일은 `make-policy` 가 쓴다.
#     재부팅(crash) 전에 반드시 sync — vfat ESP 라 안 하면 파일이 사라져 「Couldn't find pcrlock policy」가 난다.
#   - initrd 에 systemd-pcrphase-initrd·systemd-pcrosseparator 를 켜야 이벤트 로그에 750-enter-initrd·750-os-separator 가 생기고,
#     그래야 make-policy 가 PCR 7 을 보호 대상에 남긴다(없으면 PCR 7 이 조용히 빠져 PCR 15 만 남는다 — 보호가 사실상 없음).
#   - 루트가 영구(persistentRoot)여야 한다: /var/lib/systemd/pcrlock.json(NV 인덱스 정보)이 재부팅 뒤에도 있어야 정책 갱신이 같은 NV 를 쓴다.
#   - machine-id 를 고정: credential 파일 이름이 pcrlock.<machine-id>.cred 라서 부팅마다 바뀌면 옛 파일이 쌓인다.
#   - OVMF 는 dbx 쓰기를 한 번만 반영한다(두 번째 쓰기는 종료 코드 0 이지만 무시됨). 그래서 시나리오당 dbx 변경은 한 번.
{
  pkgs,
  lz,
  scenario,
  ...
}: let
  common = "${lz}/nix/tests/lanzaboote/common";
  pcrlock = "${pkgs.systemd}/lib/systemd/systemd-pcrlock";
in {
  name = "sb-pcrlock-${scenario}";

  nodes.machine = {
    config,
    pkgs,
    lib,
    ...
  }: {
    lanzabooteTest.persistentRoot = true;
    boot.initrd.systemd.enable = true;
    virtualisation.tpm.enable = true;
    virtualisation.emptyDiskImages = [64];
    environment.systemPackages = [pkgs.cryptsetup pkgs.tpm2-tools pkgs.efitools pkgs.openssl];

    # 데이터 볼륨(/dev/vdb)을 initrd 에서 TPM+PIN 으로 연다. 열리지 않아도 부팅은 계속(nofail).
    boot.initrd.luks.devices.cryptdata = {
      device = "/dev/vdb";
      crypttabExtraOpts = ["tpm2-device=auto" "nofail" "tries=1" "timeout=30s"];
    };
    fileSystems."/data" = {
      device = "/dev/mapper/cryptdata";
      fsType = "ext4";
      options = ["nofail" "x-systemd.device-timeout=30s"];
    };

    # initrd 의 pcrphase 유닛·모듈·정책 불일치 경고는 실제 설정(luks mod)과 같은 파일을 쓴다 — 시험이 실제 설정을 검증하도록
    imports = [
      "${common}/lanzaboote.nix"
      ({
        config,
        pkgs,
        lib,
        ...
      }:
        import ../../../lib/luks-tpm2.nix {
          inherit lib pkgs config;
          name = "cryptdata";
        })
    ];

    environment.etc.machine-id.text = "0123456789abcdef0123456789abcdef\n";
    # dbx 를 바꿀 때 서명에 쓰는 시험용 KEK(lanzaboote 시험 고정 키)
    environment.etc."test-kek".source = "${lz}/nix/tests/fixtures/uefi-keys/keys/KEK";
  };

  testScript = {nodes, ...}:
    (import "${common}/image-helper.nix" {inherit (nodes) machine;})
    + ''
      KEK = "/etc/test-kek"
      DBX = "/sys/firmware/efi/efivars/dbx-d719b2cb-3d3a-4596-a3bc-dad00e67656f"

      def pcr_refresh():
          # 현재 EFI 변수로 「다음 부팅」의 PCR 7 을 예측해 정책(NV·ESP 의 credential)을 갱신한다
          for sub in ["lock-secureboot-policy", "lock-secureboot-authority", "make-policy"]:
              machine.succeed("${pcrlock} " + sub + " 2>&1")
          machine.succeed("sync")

      def reboot():
          machine.succeed("sync")   # ESP(vfat) 의 credential 이 디스크에 내려가야 한다
          machine.crash()
          machine.start()

      def unlock_with_pin():
          machine.wait_for_console_text("PIN")
          machine.send_console("1234\n")

      def data_mounted():
          return machine.execute("mount | grep -q 'cryptdata on /data'")[0] == 0

      def dbx_change():
          # 시험용 해시로 dbx 를 만든다(KEK 로 서명한 인증 변수 쓰기). OVMF 는 한 번만 반영한다.
          machine.succeed("cd /tmp && echo 1 > h.bin && hash-to-efi-sig-list h.bin d.esl")
          machine.succeed(f"cd /tmp && sign-efi-sig-list -t '2030-01-01 00:00:01' -k {KEK}/KEK.key -c {KEK}/KEK.pem dbx d.esl d.auth")
          machine.succeed("cd /tmp && efi-updatevar -f d.auth dbx")
          machine.succeed(f"test -e {DBX}")

      machine.wait_for_unit("multi-user.target")
      machine.succeed("echo -n supersecret | cryptsetup luksFormat -q --iter-time=1 /dev/vdb -")
      machine.succeed("echo -n supersecret | cryptsetup luksOpen -q /dev/vdb cryptdata")
      machine.succeed("mkfs.ext4 /dev/mapper/cryptdata; systemctl stop data.mount || true; sleep 1; cryptsetup luksClose cryptdata")
      pcr_refresh()
      out = machine.succeed("${pcrlock} make-policy 2>&1")
      assert "PCR 7 (secure-boot-policy) matches" in out, "PCR 7 이 정책에서 빠졌다:\n" + out
      machine.succeed("PASSWORD=supersecret NEWPIN=1234 systemd-cryptenroll --tpm2-device=auto --tpm2-pcrlock=/var/lib/systemd/pcrlock.json --tpm2-with-pin=yes /dev/vdb 2>&1")

      with subtest("A: 기준선 — 등록 직후 재부팅하면 PIN 만으로 열린다"):
          reboot()
          unlock_with_pin()
          machine.wait_for_unit("multi-user.target")
          machine.wait_until_succeeds("mount | grep -q 'cryptdata on /data'", timeout=60)

      ${
        if scenario == "positive"
        then ''
          with subtest("C: 양성 — dbx 를 바꾼 직후 재부팅 전에 정책을 갱신하면 PIN 만으로 열린다"):
              dbx_change()
              pcr_refresh()
              reboot()
              unlock_with_pin()
              machine.wait_for_unit("multi-user.target")
              machine.wait_until_succeeds("mount | grep -q 'cryptdata on /data'", timeout=60)
        ''
        else ''
          with subtest("B: 음성 — dbx 만 바꾸고 정책을 갱신하지 않으면 TPM 이 거부한다"):
              dbx_change()
              reboot()
              unlock_with_pin()
              # 이 문구가 tpmFailWarning 이 잡을 신호다
              machine.wait_for_console_text("does not match current system state")
              machine.wait_for_unit("multi-user.target")
              assert not data_mounted(), "정책 갱신 없이 열렸다"
              # luks.tpmFailWarning 의 경고가 화면(콘솔)과 저널에 나갔다
              machine.succeed("journalctl -b -u tpm-fail-warning | grep -q 'the TPM refused to unlock this disk'")

          with subtest("D1: B 이후에는 옛 정책을 만족하지 못해 정책 갱신(make-policy)도 거부된다"):
              status, out = machine.execute("${pcrlock} lock-secureboot-policy 2>&1 && ${pcrlock} lock-secureboot-authority 2>&1 && ${pcrlock} make-policy 2>&1")
              assert status != 0, "B 이후인데 make-policy 가 성공했다:\n" + out

          with subtest("D2: 복구 — remove-policy 후 복구 암호로 TPM 슬롯을 다시 등록하면 PIN 으로 열린다"):
              machine.succeed("${pcrlock} remove-policy 2>&1")
              pcr_refresh()
              machine.succeed("PASSWORD=supersecret NEWPIN=1234 systemd-cryptenroll --wipe-slot=tpm2 --tpm2-device=auto --tpm2-pcrlock=/var/lib/systemd/pcrlock.json --tpm2-with-pin=yes /dev/vdb 2>&1")
              reboot()
              unlock_with_pin()
              machine.wait_for_unit("multi-user.target")
              machine.wait_until_succeeds("mount | grep -q 'cryptdata on /data'", timeout=60)
        ''
      }
    '';
}
