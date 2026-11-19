# `nixseal recover` 를 ISO 와 같은 도구(core/lib/nixseal-iso.nix)로, 실제 LUKS2+btrfs(@)+vfat ESP 가 있는 대상 디스크에 돌리는 VM 시험(plan/nixseal-recover §6 단계 4).
# 대상은 lanzaboote 가 설치된 실제 NixOS 시스템(nixos-install)이다 — 오프라인 nixos-enter 재생성(switch-to-configuration boot)이 실제로 ESP 를 만드는지 본다.
# 한계(시험 틀의 대체물): ISO 의 / 가 tmpfs 라는 점은 findmnt 가짜(NIXSEAL_FINDMNT)로 흉내 낸다(그 판별은 ISO 소스로 따로 확인), LUKS 암호는 cryptsetup 가짜(CRYPTSETUP)로 키 파일을 먹인다,
# 펌웨어 NVRAM(efibootmgr)은 BIOS VM 이라 없다, USB 는 두 번째 가상 디스크다.
{
  lz,
  nixseal,
  target, # 대상 시스템의 toplevel(lanzaboote + LUKS 루트 + btrfs @ + vfat /boot)
  ...
}: {
  name = "sb-recover";
  nodes.rescue = {
    lib,
    pkgs,
    ...
  }: {
    virtualisation.memorySize = 3072;
    virtualisation.emptyDiskImages = [4096 1024]; # vdb: 대상 디스크, vdc: 증거를 둘 「USB」
    virtualisation.additionalPaths = [target];
    environment.systemPackages = [nixseal pkgs.parted pkgs.btrfs-progs pkgs.dosfstools pkgs.cryptsetup pkgs.sbctl pkgs.e2fsprogs pkgs.openssl];
    nix.settings.substituters = lib.mkForce [];
  };

  testScript = ''
    CS_SHIM = """#!/bin/sh
    if [ "$1" = open ]; then shift; exec cryptsetup open --key-file /root/pw "$@"; fi
    exec cryptsetup "$@"
    """
    FM_SHIM = """#!/bin/sh
    if [ "$*" = "-no FSTYPE /" ]; then echo tmpfs; exit 0; fi
    exec findmnt "$@"
    """
    ENV = "LC_ALL=C.UTF-8 CRYPTSETUP=/root/cs-shim NIXSEAL_FINDMNT=/root/fm-shim"

    def recover(answers, extra="", env=ENV):
        return rescue.execute(f"rm -f /tmp/rc; printf '{answers}' | {env} nixseal recover --evidence-dir /usb {extra} > /tmp/out 2>&1 && echo 0 > /tmp/rc || echo $? > /tmp/rc")

    def rc():
        return int(rescue.succeed("cat /tmp/rc").strip())

    def esp_has(path):
        rescue.succeed("mkdir -p /esp; mount -o ro /dev/vdb1 /esp")
        r = rescue.execute(f"test -e /esp/{path}")[0] == 0
        rescue.succeed("umount /esp")
        return r

    def attach_target():
        rescue.succeed("cryptsetup open --key-file /root/pw /dev/vdb2 cryptroot")
        rescue.succeed("mount -o subvol=@ /dev/mapper/cryptroot /mnt && mount /dev/vdb1 /mnt/boot")

    def detach_target():
        rescue.succeed("sync; umount -R /mnt; cryptsetup close cryptroot")

    rescue.start()
    rescue.wait_for_unit("multi-user.target")
    rescue.succeed(f"printf '%s' '{CS_SHIM}' > /root/cs-shim; printf '%s' '{FM_SHIM}' > /root/fm-shim; chmod +x /root/cs-shim /root/fm-shim")

    # ── 준비: 대상 디스크(GPT: ESP + cryptroot) · LUKS2 · btrfs @ · vfat(라벨·볼륨 ID 고정) · 서명 키 · nixos-install ──
    rescue.succeed("mkfs.ext4 -q /dev/vdc; mkdir -p /usb; mount /dev/vdc /usb")
    rescue.succeed("parted -s /dev/vdb mklabel gpt mkpart ESP fat32 1MiB 257MiB set 1 esp on mkpart cryptroot 257MiB 100% name 2 cryptroot")
    rescue.succeed("udevadm settle")
    rescue.succeed("mkdir -p /mnt; printf hunter2 > /root/pw")
    rescue.succeed("cryptsetup luksFormat --batch-mode --type luks2 --uuid aaaaaaaa-0000-4000-8000-000000000001 --pbkdf pbkdf2 --pbkdf-force-iterations 1000 --key-file /root/pw /dev/vdb2")
    rescue.succeed("cryptsetup open --key-file /root/pw /dev/vdb2 cryptroot")
    rescue.succeed("mkfs.btrfs -q /dev/mapper/cryptroot; mount /dev/mapper/cryptroot /mnt; btrfs subvolume create /mnt/@; umount /mnt")
    rescue.succeed("mount -o subvol=@ /dev/mapper/cryptroot /mnt; mkfs.vfat -F 32 -n NIXBOOT -i 1234ABCD /dev/vdb1; mkdir -p /mnt/boot; mount /dev/vdb1 /mnt/boot")
    # 서명 키: lanzaboote 는 <pkiBundle>/keys/db/db.{key,pem} 만 읽는다(sbctl 은 이 환경에서 /mnt 아래에 못 써서 openssl 로 만든다)
    rescue.succeed("d=/mnt/var/lib/sbctl/keys/db; mkdir -p $d; openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj /CN=test-db/ -keyout $d/db.key -out $d/db.pem; ls $d")
    rescue.succeed("nixos-install --root /mnt --system ${target} --no-root-passwd --no-channel-copy 2>&1 | tail -20")
    assert rescue.execute("ls /mnt/boot/EFI/Linux/*.efi")[0] == 0, "설치 직후 UKI 가 있어야 한다"
    good = rescue.succeed("cd /mnt/boot && find . -type f | sort | sha256sum").strip()
    rescue.succeed("tar -C /mnt/boot -cf /usb/esp-backup-good.tar .")

    # ── 공격 흉내: 낯선 파일 + 기존 UKI 변조 ──
    rescue.succeed("echo evil > /mnt/boot/EFI/Linux/evil.efi; f=$(ls /mnt/boot/EFI/Linux/*.efi | head -1); echo x >> \"$f\"")
    detach_target()
    assert esp_has("EFI/Linux/evil.efi")

    # ── 1. ISO 가 아닌 환경(이 VM 의 / 는 ext4): 거부하고 아무것도 바꾸지 않는다 ──
    recover("아니오\\n", env="LC_ALL=C.UTF-8 CRYPTSETUP=/root/cs-shim")
    assert rc() != 0 and esp_has("EFI/Linux/evil.efi"), rescue.succeed("cat /tmp/out")

    # ── 2. 갈래 질문에 「예」: 전부 엎기 안내 후 종료 코드 3, 아무것도 안 바뀜 ──
    recover("예\\n")
    assert rc() == 3 and esp_has("EFI/Linux/evil.efi"), rescue.succeed("cat /tmp/out")
    assert "luks reseal" in rescue.succeed("cat /tmp/out")

    # ── 3. 정상 경로: 「아니오」→ ESP 경로 확인 → 포맷 확인 → 증거 보관·포맷·재생성 ──
    recover("아니오\\n/dev/vdb1\\n포맷\\n")
    out = rescue.succeed("cat /tmp/out")
    assert rc() == 0, out
    assert not esp_has("EFI/Linux/evil.efi"), "포맷했으므로 낯선 파일이 없어야 한다"
    rescue.succeed("ls /usb/esp-evidence-*.tar /usb/esp-evidence-*.txt")
    assert "evil.efi" in rescue.succeed("tar -tf /usb/esp-evidence-*.tar"), "증거 tar 에 포맷 전 내용이 있어야 한다"
    assert rescue.succeed("blkid -s UUID -o value /dev/vdb1").strip() == "1234-ABCD", "볼륨 ID 유지"
    assert rescue.succeed("blkid -s LABEL -o value /dev/vdb1").strip() == "NIXBOOT", "라벨 유지"
    attach_target()
    rescue.succeed("ls /mnt/boot/EFI/Linux/*.efi")
    assert rescue.succeed("cd /mnt/boot && find . -type f | sort | sha256sum").strip() == good, "재생성한 ESP 의 파일 구성이 설치 직후와 같아야 한다"
    detach_target()
    assert "경고: ESP 에 UKI" not in out

    # ── 4. --from-backup: 지정한 esp-backup 을 복원(재생성 없이) / esp-evidence-* 는 거부 ──
    rescue.succeed("mkdir -p /esp; mount /dev/vdb1 /esp; echo evil > /esp/EFI/Linux/evil2.efi; umount /esp")
    recover("아니오\\n/dev/vdb1\\n포맷\\n", extra="--from-backup /usb/esp-evidence-*.tar")
    assert rc() != 0 and esp_has("EFI/Linux/evil2.efi"), "증거 tar 는 복원을 거부해야 한다(ESP 불변)"
    recover("아니오\\n/dev/vdb1\\n포맷\\n", extra="--from-backup /usb/esp-backup-good.tar")
    assert rc() == 0, rescue.succeed("cat /tmp/out")
    assert not esp_has("EFI/Linux/evil2.efi") and esp_has("EFI")
  '';
}
