#!/usr/bin/env python3
"""nixseal recover 가드 시험 — 가짜 외부 명령(호출을 기록)으로 「순서를 어기면 디스크를 건드리지 않는다」를 검증한다. root·디스크·ISO 불필요.
지키는 것: 갈래 질문 → 증거 보관 성공 → 장치 확인·포맷 확인 → 그 뒤에만 포맷, 서명 키·NixOS 루트·vfat 확인 전에는 아무 것도 안 지움, 재생성 실패 시 자동 복원 없음.
실행: python3 -I core/scripts/tests/test_nixseal_recover.py   (VM·ISO 에서의 실제 동작은 plan/nixseal-recover §5·§6 의 B 시험)"""
import importlib.util, os, shutil, subprocess, sys, tempfile, io, contextlib

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("nixseal", os.path.join(os.path.dirname(HERE), "nixseal.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
os.environ["NIXSEAL_NO_SUDO"] = "1"
n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


ESP = "/dev/disk/by-uuid/ABCD-1234"


class World:
    """한 번의 recover 실행을 위한 가짜 환경: 파일(대상 루트)·명령 응답·호출 기록."""

    def __init__(self, **kw):
        self.tmp = tempfile.mkdtemp()
        self.mnt = os.path.join(self.tmp, "mnt"); os.makedirs(os.path.join(self.mnt, "etc"))
        self.evid = os.path.join(self.tmp, "usb"); os.makedirs(self.evid)
        self.calls = []
        self.mounted = set()
        self.o = dict(iso=True, evid_fs="vfat", evid_src="/dev/sdb1", mapper_open=False, nixos=True, key=True, esp_type="vfat",
                      tar_c=0, tar_t=0, tar_x=0, mkfs=0, regen=0, esp_ro_mount=0, new_mount=0, umount_esp=0, still_mounted=False,
                      fstab=True, cryptsetup_open=0, dd=0)
        self.o.update(kw)
        if self.o["fstab"]:
            open(os.path.join(self.mnt, "etc/fstab"), "w").write(
                "/dev/mapper/cryptroot / btrfs subvol=@,compress=zstd 0 0\n/dev/mapper/cryptroot /home btrfs subvol=@home 0 0\n"
                f"{ESP} /boot vfat umask=0077 0 2\n/dev/mapper/cryptroot /swap swap defaults 0 0\n")
        if self.o["nixos"]:
            open(os.path.join(self.mnt, "etc/NIXOS"), "w").write("")
        if self.o["key"]:
            kd = os.path.join(self.mnt, "var/lib/sbctl/keys/db"); os.makedirs(kd); open(os.path.join(kd, "db.key"), "w").write("k")

    def names(self):
        return [c[0] for c in self.calls]

    def has(self, name, *sub):
        return self.idx(name, *sub) is not None

    def idx(self, name, *sub):
        for i, c in enumerate(self.calls):
            if c[0] == name and all(any(s in a for a in c[1]) for s in sub):
                return i
        return None

    def x(self, name, args, capture=True, input_text=None):
        args = [str(a) for a in args]
        self.calls.append((name, args))
        o = self.o
        R = lambda rc=0, out="", err="": subprocess.CompletedProcess([name] + args, rc, out, err)
        if name == "findmnt":
            if args[:3] == ["-no", "FSTYPE", "/"]:
                return R(0, "tmpfs\n" if o["iso"] else "btrfs\n")
            return R(0, f"{o['evid_fs']} {o['evid_src']}\n")
        if name == "cryptsetup":
            if args[0] == "status":
                return R(0 if o["mapper_open"] else 4)
            if args[0] == "open":
                return R(o["cryptsetup_open"])
            return R(0)
        if name == "mount":
            if "vfat" in args:
                tgt = args[-1]
                if "ro,nodev,nosuid,noexec,fmask=0137,dmask=0027" in args:
                    if o["esp_ro_mount"] == 0: self.mounted.add(tgt)
                    return R(o["esp_ro_mount"])
                if o["new_mount"] == 0: self.mounted.add(tgt)
                return R(o["new_mount"])
            return R(0)
        if name == "umount":
            if args[0] == "-R":
                return R(0)
            if o["umount_esp"] == 0 and not o["still_mounted"]: self.mounted.discard(args[0])
            return R(o["umount_esp"])
        if name == "mountpoint":
            return R(0 if (args[-1] in self.mounted or o["still_mounted"]) else 1)
        if name == "blkid":
            return R(0, f"TYPE={o['esp_type']}\nLABEL=ESP\nUUID=ABCD-1234\n")
        if name == "lsblk":
            return R(0, "NAME SIZE\nsda1 1G\n")
        if name == "tar":
            if "-cf" in args:
                if o["tar_c"] == 0:
                    open(args[args.index("-cf") + 1], "wb").write(b"x" * 100)
                return R(o["tar_c"])
            if "-tf" in args:
                return R(o["tar_t"])
            return R(o["tar_x"])
        if name == "efibootmgr":
            return R(0, "BootCurrent: 0001\nBoot0001* rEFInd\n")
        if name == "mkfs.vfat":
            return R(o["mkfs"])
        if name == "nixos-enter":
            if "switch-to-configuration" in args[-1]:
                if o["regen"] == 0:
                    os.makedirs(os.path.join(self.mnt, "boot/EFI/Linux"), exist_ok=True)
                    open(os.path.join(self.mnt, "boot/EFI/Linux/nixos-generation-1.efi"), "w").write("x")
                return R(o["regen"])
            return R(0, "✓ signed\n")
        if name == "blockdev":
            return R(0, "1073741824\n")
        if name == "dd":
            return R(o["dd"])
        return R(0)

    def run(self, answers, *args):
        M._x = self.x
        M.MNT = self.mnt
        M.EFIVARS = os.path.join(self.tmp, "efivars"); os.makedirs(M.EFIVARS, exist_ok=True)
        it = iter(answers)
        M._ask = lambda p: next(it, "")
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                M.cmd_recover(list(args))
            rc = 0
        except SystemExit as e:
            rc = e.code or 0
        self.out, self.err = out.getvalue(), err.getvalue()
        return rc

    def done(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


GOOD = ["아니오", ESP, M.FORMAT_ACK]
DESTRUCTIVE = ("mkfs.vfat",)


def w(**kw):
    return World(**kw)


def evid_args(wd):
    return ["--evidence-dir", wd.evid]


# ── 정상 흐름 ──
wd = w(); rc = wd.run(GOOD, *evid_args(wd))
check("정상: 종료 0", rc == 0, f"{rc} {wd.err[:200]}")
i_tar, i_um, i_mk, i_regen = wd.idx("tar", "-cf"), wd.idx("umount", wd.mnt + "/boot"), wd.idx("mkfs.vfat"), wd.idx("nixos-enter", "switch-to-configuration")
check("정상: 증거 tar → ESP 내리기 → 포맷 → 재생성 순서", None not in (i_tar, i_um, i_mk, i_regen) and i_tar < i_um < i_mk < i_regen, str(wd.names()))
mk = wd.calls[i_mk][1]
check("정상: 포맷은 FAT32·기존 라벨(ESP)·볼륨 ID(ABCD1234) 유지", mk == ["-F", "32", "-n", "ESP", "-i", "ABCD1234", ESP], str(mk))
ro = [c for c in wd.calls if c[0] == "mount" and "vfat" in c[1]][0][1]
check("정상: 처음 마운트는 읽기 전용(ro,nodev,nosuid,noexec)", "ro,nodev,nosuid,noexec,fmask=0137,dmask=0027" in ro, str(ro))
evs = os.listdir(wd.evid)
check("정상: 증거 tar·txt 가 저장됨", any(f.startswith("esp-evidence-") and f.endswith(".tar") for f in evs) and any(f.endswith(".txt") for f in evs), str(evs))
txt = open(os.path.join(wd.evid, [f for f in evs if f.endswith(".txt")][0])).read() if any(f.endswith(".txt") for f in evs) else ""
check("정상: 증거 txt 에 라벨·볼륨 ID·efibootmgr", "LABEL=ESP" in txt and "UUID=ABCD-1234" in txt and "Boot0001" in txt, txt[:200])
check("정상: 끝에 TPM 안내(첫 부팅은 복구 암호, refresh-policy / remove-policy)", "복구 암호" in wd.out and "refresh-policy" in wd.out and "remove-policy" in wd.out)
check("정상: 끝에 umount -R·cryptsetup close(정리)", wd.has("umount", "-R") and wd.has("cryptsetup", "close"))
check("정상: TPM 관련 명령은 부르지 않음(systemd-pcrlock·cryptenroll)", not any(c[0] in ("systemd-pcrlock", "systemd-cryptenroll") for c in wd.calls))
check("정상: swap·ESP 항목은 마운트하지 않고 /home 은 마운트", not wd.has("mount", "--mkdir") or (any("/home" in a for a in [c[1][-1] for c in wd.calls if c[0] == "mount" and "--mkdir" in c[1]]) and not any(a.endswith("/swap") or a.endswith("/boot") for a in [c[1][-1] for c in wd.calls if c[0] == "mount" and "--mkdir" in c[1]])))
wd.done()

# ── 디스크를 건드리기 전 거부 ──
wd = w(iso=False); rc = wd.run(GOOD, *evid_args(wd))
check("ISO 가 아니면 거부(종료 1)·아무 것도 안 부름", rc == 1 and wd.names() == ["findmnt"], f"{rc} {wd.names()}")
wd.done()
wd = w(evid_fs="tmpfs"); rc = wd.run(GOOD, *evid_args(wd))
check("증거 경로가 RAM(tmpfs)이면 거부·루트도 안 엶", rc == 1 and not wd.has("cryptsetup", "open"), f"{rc}")
wd.done()
wd = w(); rc = wd.run(GOOD)
check("증거 경로도 --no-evidence 도 없으면 거부(종료 2)", rc == 2 and not wd.has("cryptsetup", "open"), f"{rc}")
wd.done()
wd = w(mapper_open=True); rc = wd.run(GOOD, *evid_args(wd))
check("대상 매퍼가 이미 열려 있으면 거부", rc == 1 and not wd.has("cryptsetup", "open") and not wd.has("mkfs.vfat"), f"{rc}")
wd.done()
wd = w(); rc = wd.run(GOOD, "--bogus")
check("알 수 없는 옵션 거부(종료 2)", rc == 2)
wd.done()

# ── 갈래 질문: 복구 암호/FIDO2 입력 가능성이 있으면 아무 것도 바꾸지 않고 멈춘다 ──
for ans in ("예", "모르겠음", "", "아니요"):
    wd = w(); rc = wd.run([ans] + GOOD[1:], *evid_args(wd))
    check(f"갈래 질문 「{ans or '(빈 입력)'}」: 종료 3·루트도 안 엶·포맷 안 함·전부 엎기 안내", rc == 3 and not wd.has("cryptsetup", "open") and not wd.has("mkfs.vfat") and "reseal" in wd.out, f"{rc} {wd.names()}")
    wd.done()

# ── 루트·키·장치 확인: 실패하면 ESP 를 건드리지 않는다(증거도 안 만듦) ──
def untouched(wd):
    return not wd.has("mkfs.vfat") and not wd.has("tar", "-cf") and not wd.has("nixos-enter", "switch-to-configuration")
wd = w(key=False); rc = wd.run(GOOD, *evid_args(wd))
check("서명 키가 없으면 중단(종료 1)·ESP 안 건드림·--from-backup 안내", rc == 1 and untouched(wd) and "--from-backup" in wd.err, f"{rc} {wd.err[:160]}")
wd.done()
wd = w(nixos=False); rc = wd.run(GOOD, *evid_args(wd))
check("대상이 NixOS 루트가 아니면(/etc/NIXOS 없음) 중단", rc == 1 and untouched(wd), f"{rc}")
wd.done()
wd = w(fstab=False); rc = wd.run(GOOD, *evid_args(wd))
check("fstab 이 없으면 중단", rc == 1 and untouched(wd), f"{rc}")
wd.done()
wd = w(esp_type="ntfs"); rc = wd.run(GOOD, *evid_args(wd))
check("ESP 장치가 vfat 이 아니면 중단", rc == 1 and untouched(wd), f"{rc}")
wd.done()
wd = w(evid_src=ESP); rc = wd.run(GOOD, *evid_args(wd))
check("증거 경로가 ESP 와 같은 장치면 거부", rc == 1 and untouched(wd), f"{rc}")
wd.done()
wd = w(); rc = wd.run(["아니오", "/dev/sda1", M.FORMAT_ACK], *evid_args(wd))
check("ESP 장치 확인에 다른 경로를 입력하면 취소(마운트·증거·포맷 안 함)", rc == 1 and untouched(wd) and not wd.has("mount", "vfat"), f"{rc}")
wd.done()
wd = w(esp_ro_mount=1); rc = wd.run(GOOD, *evid_args(wd))
check("ESP 를 읽기 전용으로 못 열면 중단(포맷 안 함)", rc == 1 and untouched(wd), f"{rc}")
wd.done()
wd = w(cryptsetup_open=1); rc = wd.run(GOOD, *evid_args(wd))
check("루트를 못 열면 중단", rc == 1 and untouched(wd), f"{rc}")
wd.done()

# ── 증거 보관 실패 → ESP 그대로 ──
wd = w(tar_c=1); rc = wd.run(GOOD, *evid_args(wd))
check("증거 tar 저장 실패면 포맷하지 않음(ESP 그대로)", rc == 1 and not wd.has("mkfs.vfat") and not wd.has("umount", wd.mnt + "/boot"), f"{rc} {wd.names()}")
wd.done()
wd = w(tar_t=1); rc = wd.run(GOOD, *evid_args(wd))
check("저장한 증거 tar 를 읽지 못하면 포맷하지 않음", rc == 1 and not wd.has("mkfs.vfat"), f"{rc}")
wd.done()
wd = w(); rc = wd.run(GOOD, "--no-evidence")
check("--no-evidence: tar -cf 없이 진행(포맷은 함)", rc == 0 and not wd.has("tar", "-cf") and wd.has("mkfs.vfat"), f"{rc}")
wd.done()
wd = w(); rc = wd.run(GOOD, *evid_args(wd), "--evidence-image")
check("--evidence-image: dd 로 이미지를 포맷 전에 저장", rc == 0 and wd.idx("dd") is not None and wd.idx("dd") < wd.idx("mkfs.vfat"), f"{rc} {wd.names()}")
wd.done()
wd = w(); _du = shutil.disk_usage; shutil.disk_usage = lambda p: type("D", (), {"free": 1000})()
rc = wd.run(GOOD, *evid_args(wd), "--evidence-image"); shutil.disk_usage = _du
check("--evidence-image: USB 공간이 모자라면 포맷하지 않음", rc == 1 and not wd.has("mkfs.vfat") and not wd.has("dd"), f"{rc}")
wd.done()
wd = w(dd=1); rc = wd.run(GOOD, *evid_args(wd), "--evidence-image")
check("--evidence-image: dd 실패면 포맷하지 않음", rc == 1 and not wd.has("mkfs.vfat"), f"{rc}")
wd.done()

# ── 포맷 직전 확인·마운트 상태 ──
wd = w(); rc = wd.run(["아니오", ESP, "아니오"], *evid_args(wd))
check("포맷 확인 문구가 틀리면 포맷 안 함(증거는 저장됨)", rc == 1 and not wd.has("mkfs.vfat") and not wd.has("umount", wd.mnt + "/boot") and wd.has("tar", "-cf"), f"{rc}")
wd.done()
wd = w(still_mounted=True); rc = wd.run(GOOD, *evid_args(wd))
check("ESP 가 내려가지 않았으면(mountpoint 가 여전히 마운트) 포맷하지 않음", rc == 1 and not wd.has("mkfs.vfat"), f"{rc}")
wd.done()
wd = w(umount_esp=1); rc = wd.run(GOOD, *evid_args(wd))
check("ESP umount 실패면 포맷하지 않음", rc == 1 and not wd.has("mkfs.vfat"), f"{rc}")
wd.done()
wd = w(mkfs=1); rc = wd.run(GOOD, *evid_args(wd))
check("mkfs 실패는 종료 1·재생성 안 함·같은 명령 재시도 안내", rc == 1 and not wd.has("nixos-enter", "switch-to-configuration") and "다시 시도" in wd.err, f"{rc} {wd.err[:200]}")
wd.done()
wd = w(new_mount=1); rc = wd.run(GOOD, *evid_args(wd))
check("새 ESP 를 마운트하지 못하면 재생성 안 함", rc == 1 and not wd.has("nixos-enter", "switch-to-configuration"), f"{rc}")
wd.done()

# ── 재생성 실패: 자동 복원으로 넘어가지 않고 힌트만 ──
wd = w(regen=1); rc = wd.run(GOOD, *evid_args(wd))
check("재생성 실패: 종료 1·백업 자동 복원(tar -xf) 안 함·--from-backup 힌트", rc == 1 and not wd.has("tar", "-xf") and "--from-backup" in wd.err and "비어 있습니다" in wd.err, f"{rc} {wd.err[:200]}")
check("재생성 실패해도 정리(umount -R·close)", wd.has("umount", "-R") and wd.has("cryptsetup", "close"))
wd.done()

# ── --from-backup: 사용자가 지정한 esp-backup 만, 재생성 없이 복원 ──
wd = w(); bk = os.path.join(wd.tmp, "esp-backup-20261101.tar"); open(bk, "w").write("x")
rc = wd.run(GOOD, *evid_args(wd), "--from-backup", bk)
check("--from-backup: 포맷 뒤 tar -xf 로 복원·재생성(switch-to-configuration)은 안 함", rc == 0 and wd.idx("mkfs.vfat") < wd.idx("tar", "-xf") and not wd.has("nixos-enter", "switch-to-configuration"), f"{rc} {wd.names()}")
wd.done()
wd = w(key=False); bk = os.path.join(wd.tmp, "esp-backup-20261101.tar"); open(bk, "w").write("x")
rc = wd.run(GOOD, *evid_args(wd), "--from-backup", bk)
check("--from-backup: 서명 키가 없어도 복원 진행", rc == 0 and wd.has("tar", "-xf"), f"{rc} {wd.err[:150]}")
wd.done()
wd = w(); ev = os.path.join(wd.tmp, "esp-evidence-20261101.tar"); open(ev, "w").write("x")
rc = wd.run(GOOD, *evid_args(wd), "--from-backup", ev)
check("--from-backup: esp-evidence-* 는 거부(종료 2)·아무 것도 안 부름", rc == 2 and not wd.has("cryptsetup", "open"), f"{rc}")
wd.done()
wd = w(); rc = wd.run(GOOD, *evid_args(wd), "--from-backup", os.path.join(wd.tmp, "없음.tar"))
check("--from-backup: 파일이 없으면 거부(종료 2)", rc == 2 and not wd.has("cryptsetup", "open"), f"{rc}")
wd.done()
wd = w(tar_x=1); bk = os.path.join(wd.tmp, "esp-backup-1.tar"); open(bk, "w").write("x")
rc = wd.run(GOOD, *evid_args(wd), "--from-backup", bk)
check("--from-backup: 복원 실패는 종료 1", rc == 1, f"{rc}")
wd.done()

# ── 어떤 경로에서도 포맷 전에 증거·질문·확인이 먼저(순서 불변식) ──
wd = w(); wd.run(GOOD, *evid_args(wd))
order = wd.names()
check("불변식: 루트 열기 → ESP 읽기전용 마운트 → 증거 → 포맷", order.index("cryptsetup") < [i for i, c in enumerate(wd.calls) if c[0] == "mount" and "vfat" in c[1]][0] < wd.idx("tar", "-cf") < wd.idx("mkfs.vfat"))
wd.done()

# ── NixOS 의 /etc/fstab 은 /etc/static/fstab(절대 링크)이라 대상 루트 안에서 따라가야 한다(실제 VM 시험에서 놓쳤던 버그) ──
_d = tempfile.mkdtemp()
os.makedirs(_d + "/etc"); os.makedirs(_d + "/nix/store/x/etc")
open(_d + "/nix/store/x/etc/fstab", "w").write("UUID=1 /boot vfat umask=0077 0 0\n")
os.symlink("/nix/store/x/etc", _d + "/etc/static"); os.symlink("/etc/static/fstab", _d + "/etc/fstab")
check("fstab 이 절대 링크여도 대상 루트 안에서 찾는다", [e[1] for e in M._parse_fstab(M._in_root(_d, "etc/fstab"))] == ["/boot"])
os.symlink("../../../../etc/shadow", _d + "/etc/evil")
check("루트 밖으로 나가는 링크는 루트 안으로 가둔다", M._in_root(_d, "etc/evil").startswith(_d + "/"))
shutil.rmtree(_d)

print(f"\nnixseal-recover {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
