"""ISO 를 QEMU(UEFI/OVMF, KVM)로 부팅해 시리얼 콘솔로 `nixseal recover` 를 실제로 돌린다. 사용: QEMU_DIR=… OVMF_DIR=… isorec.py <ISO> <대상디스크.img(raw)> <USB.img(raw)> — 시험 대상 디스크는 core/scripts/tests/vm 의 `-A recoverprep` 로 만든다(README 의 절차)"""
import os, re, socket, subprocess, sys, time, shutil
HERE = os.path.dirname(os.path.abspath(__file__))
ISO, TGT, USB = sys.argv[1:4]
QEMU = os.environ["QEMU_DIR"]; OVMF = os.environ["OVMF_DIR"]  # 예: nix build nixpkgs#qemu_kvm nixpkgs#OVMF.fd --print-out-paths
import tempfile
WORK = tempfile.mkdtemp(prefix="isorec-")
shutil.copy(OVMF + "/FV/OVMF_VARS.fd", WORK + "/vars.fd"); os.chmod(WORK + "/vars.fd", 0o644)
sock_path = WORK + "/ser.sock"
if os.path.exists(sock_path): os.remove(sock_path)
cmd = [QEMU + "/bin/qemu-system-x86_64", "-enable-kvm", "-cpu", "host", "-machine", "q35", "-m", "6144", "-smp", "4",
       "-drive", f"if=pflash,format=raw,readonly=on,file={OVMF}/FV/OVMF_CODE.fd", "-drive", f"if=pflash,format=raw,file={WORK}/vars.fd",
       "-cdrom", ISO, "-boot", "order=d",
       "-drive", f"file={TGT},format=raw,if=virtio,snapshot=on", "-drive", f"file={USB},format=raw,if=virtio,snapshot=on",
       "-display", "none", "-serial", f"unix:{sock_path},server,nowait", "-no-reboot",
       # 모니터를 끄면(-monitor none) QEMU 에게 종료를 부탁할 통로가 없다 — 사람이 손으로 끌 때 쓰도록 QMP 소켓을 둔다
       "-qmp", f"unix:{WORK}/qmp.sock,server,nowait"]
qp = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

# 정리: 시험이 어떻게 끝나든(실패·예외·Ctrl-C·SIGTERM) 이 하네스가 띄운 QEMU 를 남기지 않는다.
import atexit, signal
def _cleanup():
    if qp.poll() is None:
        qp.terminate()
        try: qp.wait(timeout=10)
        except subprocess.TimeoutExpired:
            qp.kill(); qp.wait()
atexit.register(_cleanup)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))  # sys.exit 이라야 atexit 가 돈다
for _ in range(50):
    if os.path.exists(sock_path): break
    time.sleep(0.2)
s = socket.socket(socket.AF_UNIX); s.connect(sock_path); s.setblocking(False)
buf = ""; full = ""
def pump(t=0.3):
    global buf, full
    end = time.time() + t
    while time.time() < end:
        try:
            d = s.recv(65536)
            if not d: return False
            txt = d.decode(errors="replace"); buf += txt; full += txt
        except BlockingIOError: time.sleep(0.05)
    return True
def expect(pat, timeout=120, label=None):
    global buf
    t0 = time.time()
    while time.time() - t0 < timeout:
        pump(0.3)
        m = re.search(pat, buf)
        if m:
            out = buf[:m.end()]; buf = buf[m.end():]; return out
        if qp.poll() is not None:
            print("QEMU 종료됨", qp.returncode, qp.stderr.read().decode()[-300:]); return None
    print("타임아웃:", label or pat, "| 버퍼 끝:", repr(buf[-400:])); return None
def send(t): s.sendall(t.encode())
def clean(t): return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\r", "", t)
def run(c, timeout=60):
    send(c + "\n"); out = expect(r"READY# $", timeout, c); return clean(out or "")
fails = []
def check(name, cond):
    print(("  OK  " if cond else "  FAIL ") + name)
    if not cond: fails.append(name)

t0 = time.time()
out = expect(r"nixos-iso", 400, "ISO 셸 프롬프트")
print(f"[부팅 {time.time()-t0:.0f}s] ISO 로그인 셸:", bool(out))
pump(3); send("\n"); pump(1)
send("exec bash --norc --noprofile\n"); pump(2)
send("export PS1='READY# '; stty -echo 2>/dev/null; stty cols 200 rows 60\n")
expect(r"READY# $", 30, "bash 전환")
env = run("findmnt -no FSTYPE /; which nixseal nixos-enter mkfs.vfat efibootmgr sbctl btrfs tar 2>&1; lsblk -o NAME,SIZE,FSTYPE,PARTLABEL,LABEL | cat")
print(env)
check("ISO 의 / 가 RAM 계열 파일시스템", bool(re.search(r"^(tmpfs|overlay|squashfs)\s*$", env, re.M)))
for t in ["nixseal", "nixos-enter", "mkfs.vfat", "efibootmgr", "btrfs", "tar"]:
    check(f"PATH 에 {t}", bool(re.search(r"/bin/" + re.escape(t) + r"\s*$", env, re.M)))
usbdev = re.search(r"^(vd[a-z])\s+\S+\s+ext4", env, re.M)
print(run("sudo mkdir -p /usb"))
# USB(ext4)는 두 번째 virtio 디스크 — 장치 이름은 lsblk 로 찾는다
usb = re.search(r"^(vd[a-z])$", run("lsblk -rno NAME,FSTYPE | awk '$2==\"ext4\"{print $1}' | head -1"), re.M).group(1)
w = run("tr ':' '\\n' < <(grep -o 'PATH=[^ ]*' $(readlink -f $(which nixseal)))")
for t in ["sbctl", "dosfstools", "gnutar", "efibootmgr", "nixos-install-tools", "btrfs-progs", "cryptsetup"]:
    check(f"래퍼 PATH 에 {t}", t in w)
print("USB 장치:", usb)
print(run(f"sudo mount /dev/{usb} /usb && ls /usb | head"))
print(run("sudo mkdir -p /usb/ev"))
# ── 정상 경로 ──
send("sudo nixseal recover --evidence-dir /usb/ev\n")
o = expect(r"\[예/아니오/모르겠음\]: ", 60, "갈래 질문"); print(clean(o or "")[-600:])
send("아니오\n")
o = expect(r"Enter passphrase[^\n]*: ", 90, "LUKS 암호"); print(clean(o or "")[-300:])
send("hunter2\n")
o = expect(r"그대로 입력하세요 \((/dev/[^)]+)\): ", 120, "ESP 확인"); print(clean(o or "")[-700:])
esp = re.search(r"\((/dev/[^)]+)\): ", clean(o or "")).group(1)
send(esp + "\n")
o = expect(r"'포맷' 를 입력하세요: |계속하려면 '포맷'[^\n]*: ", 120, "포맷 확인"); print(clean(o or "")[-600:])
send("포맷\n")
o = expect(r"READY# $", 600, "recover 종료"); co = clean(o or ""); print(co[-3500:])
rc = run("echo rc=$?")
check("recover 종료 코드 0", "rc=0" in rc)
ev = run("ls /usb/ev")
check("증거 tar·txt 저장", "esp-evidence-" in ev and ".tar" in ev and ".txt" in ev)
check("증거 tar 에 포맷 전 evil.efi", "evil.efi" in run("tar -tf /usb/ev/esp-evidence-*.tar | grep evil"))
check("sbctl verify 출력이 나옴", "== sbctl verify ==" in co)
check("UKI 경고 없음", "경고: ESP 에 UKI" not in co)
check("볼륨 ID 유지(1234-ABCD)", "1234-ABCD" in run(f"sudo blkid -s UUID -o value {esp}"))
check("라벨 유지(NIXBOOT)", "NIXBOOT" in run(f"sudo blkid -s LABEL -o value {esp}"))
chk = run("sudo mkdir -p /e && sudo mount -o ro " + esp + " /e && ls /e/EFI/Linux/ && ls /e/EFI/Linux/evil.efi 2>&1; sudo umount /e")
print(chk)
check("새 ESP 에 UKI 있고 evil.efi 없음", ".efi" in chk and "No such file" in chk)
check("정리됨(/mnt 비어 있고 매퍼 닫힘)", "cryptroot" not in run("lsblk -rno NAME | grep cryptroot; ls /dev/mapper") )
send("sudo poweroff\n"); pump(3)
for _ in range(60):
    if qp.poll() is not None: break
    time.sleep(1)
open(WORK + "/serial.log", "w").write(clean(full)); print("시리얼 로그:", WORK + "/serial.log")
print("실패:", fails if fails else "없음")
