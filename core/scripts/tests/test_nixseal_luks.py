#!/usr/bin/env python3
"""nixseal 시험(luks 헤더 백업·복원 + sb 변수·enroll·dbx 논리) — 실제 cryptsetup 으로 일반 파일 이미지(root 불필요)에서 백업→손상→복원을 돌린다.
cryptsetup 이 PATH 에 없으면 건너뜀(종료 0). 실행: nix shell nixpkgs#cryptsetup -c python3 -I core/scripts/tests/test_nixseal_luks.py"""
import importlib.util, os, shutil, stat, subprocess, sys, tempfile

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LC = os.path.join(SCRIPTS, "nixseal.py")
n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


spec = importlib.util.spec_from_file_location("nixseal", LC)
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)

# 순수 파서 시험 (cryptsetup 없이)
DUMP = """LUKS header information
Keyslots:
  0: luks2
\tKey:        512 bits
\tPBKDF:      argon2id
  1: luks2
\tPBKDF:      pbkdf2
Tokens:
  0: systemd-tpm2
Digests:
  0: pbkdf2
"""
info = M.parse_slots(DUMP)
check("파서: 슬롯 2개·PBKDF", info["slots"] == [(0, "luks2", "argon2id"), (1, "luks2", "pbkdf2")], str(info))
check("파서: 토큰 1개", info["tokens"] == [(0, "systemd-tpm2")], str(info))
check("파서: 토큰 없음", M.parse_slots("Keyslots:\n  0: luks2\nTokens:\nDigests:\n")["tokens"] == [])

# ── sb: 가짜 efivars·가짜 sbctl 로 enroll/dbx 논리를 시험한다(루트·실제 펌웨어 불필요) ──
import struct
os.environ["NIXSEAL_NO_SUDO"] = "1"
fake = tempfile.mkdtemp()
efi = os.path.join(fake, "efivars"); os.makedirs(efi)
M.EFIVARS = efi
sbctl_log = os.path.join(fake, "sbctl.log")
fake_sbctl = os.path.join(fake, "sbctl")
with open(fake_sbctl, "w") as f:
    f.write("#!/bin/sh\necho \"$@\" >> %s\n" % sbctl_log)
os.chmod(fake_sbctl, 0o755)
M.SBCTL = fake_sbctl
dbx_src = os.path.join(fake, "DBXUpdate.bin")
with open(dbx_src, "wb") as f:
    f.write(b"\x11" * 100)
M.DBX_BUNDLED = dbx_src


def put(name, guid, body, attr=7):
    with open(os.path.join(efi, f"{name}-{guid}"), "wb") as f:
        f.write(struct.pack("<I", attr) + body)


def run_sb(fn, *a):
    import contextlib, io
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            fn(list(a))
        return 0
    except SystemExit as e:
        return e.code or 0


check("var_size: 없는 변수는 None", M.var_size("dbx", M.G_DB) is None)
put("SetupMode", M.G_GLOBAL, b"\x00")
check("var_byte/var_size", M.var_byte("SetupMode", M.G_GLOBAL) == 0 and M.var_size("SetupMode", M.G_GLOBAL) == 1)
# 실제 efivarfs 는 seek 를 지원하지 않는다(2026-11-19 실기에서 var_byte 가 None 이 되어 status 가 「읽지 못함」으로 나온 적 있음)
import io
class _NoSeek(io.RawIOBase):
    def __init__(self, data): self._d = io.BytesIO(data)
    def readable(self): return True
    def seekable(self): return False
    def readinto(self, b):
        chunk = self._d.read(len(b)); b[:len(chunk)] = chunk; return len(chunk)
M.open = lambda p, m="r", *a, **k: io.BufferedReader(_NoSeek(open(p, "rb").read()))
check("var_byte: seek 불가 파일(efivarfs)에서도 읽음", M.var_byte("SetupMode", M.G_GLOBAL) == 0)
del M.open
put("PK", M.G_GLOBAL, b"abc"); put("PKDefault", M.G_GLOBAL, b"abc")
check("is_factory: 같으면 True", M.is_factory("PK"))
put("PKDefault", M.G_GLOBAL, b"abd")
check("is_factory: 다르면 False", not M.is_factory("PK"))
rc = run_sb(M.cmd_sb_enroll)
check("enroll: Setup Mode 가 아니면 거부, sbctl 호출 없음", rc != 0 and not os.path.exists(sbctl_log), str(rc))
put("SetupMode", M.G_GLOBAL, b"\x01")
dbxp = os.path.join(efi, f"dbx-{M.G_DB}")
rc = run_sb(M.cmd_sb_enroll)
log = open(sbctl_log).read()
check("enroll: sbctl enroll-keys --microsoft --firmware-builtin 호출", rc == 0 and "enroll-keys --microsoft --firmware-builtin" in log, log)
check("enroll: 키만 등록하고 dbx 는 만들지 않음(dbx 는 sb dbx 몫)", not os.path.exists(dbxp))
os.remove(sbctl_log)
rc = run_sb(M.cmd_sb_enroll, "--no-firmware-builtin")
check("enroll --no-firmware-builtin: 플래그를 뺌", rc == 0 and "firmware-builtin" not in open(sbctl_log).read())
check("enroll: 알 수 없는 옵션 거부(종료 2)", run_sb(M.cmd_sb_enroll, "--dbx-only") == 2)

# ── sb dbx: 키가 등록된 User Mode 에서만, 비어 있을 때만 채운다(자동으로 하지 않는다 — 사용자가 직접) ──
put("SetupMode", M.G_GLOBAL, b"\x01")  # Setup Mode: 아직 키 등록 전
rc = run_sb(M.cmd_sb_dbx)
check("sb dbx: Setup Mode 에서는 거부(종료 1)·dbx 안 만듦", rc == 1 and not os.path.exists(dbxp), str(rc))
put("SetupMode", M.G_GLOBAL, b"\x00")  # User Mode: 키 등록 끝
M._ask = lambda p: "아니오"
rc = run_sb(M.cmd_sb_dbx)
check("sb dbx: 「집이고 바로 재부팅」 확인이 틀리면 취소·dbx 안 만듦", rc == 1 and not os.path.exists(dbxp), str(rc))
M._ask = lambda p: M.HOME_ACK
rc = run_sb(M.cmd_sb_dbx)
raw = open(dbxp, "rb").read() if os.path.exists(dbxp) else b""
check("sb dbx: 키가 있고 dbx 가 없으면 내장본을 속성 0x67 + 본문으로 씀", rc == 0 and raw[:4] == struct.pack("<I", 0x67) and raw[4:] == b"\x11" * 100, raw[:8].hex())
put("dbx", M.G_DB, b"\x22" * 10); before = open(dbxp, "rb").read()  # 내장본과 다른 기존 dbx
rc = run_sb(M.cmd_sb_dbx)
check("sb dbx: dbx 가 이미 있으면 덮어쓰지 않음", rc == 0 and open(dbxp, "rb").read() == before)
os.remove(dbxp)
M.DBX_BUNDLED = os.path.join(fake, "없음.bin")
rc = run_sb(M.cmd_sb_dbx)
check("sb dbx: 내장본이 없으면 종료 1·dbx 안 만듦", rc == 1 and not os.path.exists(dbxp), str(rc))
check("sb dbx: 알 수 없는 인자 거부(종료 2)", run_sb(M.cmd_sb_dbx, "--auto") == 2)
M.DBX_BUNDLED = dbx_src

# ── sb dbx-update: 가짜 fwupdmgr 로 확인 절차·적용 순서를 시험한다 ──
fw_log = os.path.join(fake, "fw.log"); fw_state = os.path.join(fake, "fw.state")
fake_fw = os.path.join(fake, "fwupdmgr")
with open(fake_fw, "w") as f:
    f.write("#!/bin/sh\necho \"$@\" >> %s\nif [ \"$1\" = get-updates ]; then\n  if [ -f %s ]; then echo '  New version: 20990101'; exit 0; fi\n  echo 'Nothing to do'; exit 2\nfi\nif [ \"$1\" = update ]; then rm -f %s; fi\nexit 0\n" % (fw_log, fw_state, fw_state))
os.chmod(fake_fw, 0o755)
M.FWUPDMGR = fake_fw
fwdir = os.path.join(fake, "fwdir"); os.makedirs(fwdir); M.FWUPD_DIR = fwdir
def fw_calls():
    return open(fw_log).read() if os.path.exists(fw_log) else ""
put("dbx", M.G_DB, b"\x22" * 10)
open(fw_state, "w").write("x")
open(os.path.join(fwdir, "last-result"), "w").write("  New version: 20990101\n")  # 알림을 일으키는 낡은 결과
M._ask = lambda p: "아니오"
rc = run_sb(M.cmd_sb_dbx_update)
check("dbx-update: 확인이 틀리면 update 를 호출하지 않음", rc == 1 and "update -y" not in fw_calls(), fw_calls())
M._ask = lambda p: M.HOME_ACK
rc = run_sb(M.cmd_sb_dbx_update)
check("dbx-update: 확인 뒤에 fwupdmgr update 호출 + 결과 파일을 다시 씀(알림이 멈춤)", rc == 0 and "update -y --no-reboot-check" in fw_calls() and "New version" not in open(os.path.join(fwdir, "last-result")).read(), fw_calls())
os.remove(fw_log)
rc = run_sb(M.cmd_sb_dbx_update)
check("dbx-update: 갱신이 없으면 묻지도 않고 update 도 안 함", rc == 0 and "update -y" not in fw_calls())
os.remove(dbxp)
open(fw_state, "w").write("x")
rc = run_sb(M.cmd_sb_dbx_update)
check("dbx-update: dbx 가 비어 있으면 거부(먼저 sb dbx)·update 안 함", rc == 1 and "update -y" not in fw_calls())

# ── tpm(pcrlock): 가짜 systemd-pcrlock·systemd-cryptenroll 로 확인 절차·호출 순서·PCR 7 누락 처리를 시험한다(root·TPM 불필요) ──
import contextlib, json


def run_sb_out(fn, *a):
    """run_sb 와 같지만 (종료코드, stdout, stderr) 를 돌려준다."""
    o, e = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(o), contextlib.redirect_stderr(e):
            fn(list(a))
        rc = 0
    except SystemExit as x:
        rc = x.code or 0
    return rc, o.getvalue(), e.getvalue()


pl_log = os.path.join(fake, "pcrlock.log")
pl_mode = os.path.join(fake, "pcrlock.mode")   # 비어 있으면 정상 / "nopcr7" = PCR 7 빠진 출력 / "fail:<서브명령>" = 그 서브명령 실패
fake_pl = os.path.join(fake, "systemd-pcrlock")
with open(fake_pl, "w") as f:
    f.write("""#!/bin/sh
echo "$1" >> %s
mode=$(cat %s 2>/dev/null)
if [ "$mode" = "fail:$1" ]; then echo "boom $1" >&2; exit 1; fi
if [ "$1" = make-policy ]; then
  if [ "$mode" = nopcr7 ]; then echo "PCRs in protection mask: 3 (external-config), 15 (system-identity)"
  else echo "PCRs in protection mask: 3 (external-config), 7 (secure-boot-policy), 15 (system-identity)"; fi
fi
exit 0
""" % (pl_log, pl_mode))
os.chmod(fake_pl, 0o755)
ce_log = os.path.join(fake, "cryptenroll.log")
fake_ce = os.path.join(fake, "systemd-cryptenroll")
with open(fake_ce, "w") as f:
    f.write("#!/bin/sh\necho \"$@\" >> %s\nexit 0\n" % ce_log)
os.chmod(fake_ce, 0o755)
M.NIXSEAL_PCRLOCK = None
os.environ["NIXSEAL_PCRLOCK"] = fake_pl
M.CRYPTENROLL = fake_ce
M.PCRLOCK_JSON = os.path.join(fake, "pcrlock.json")
M.ESP_CRED_DIR = os.path.join(fake, "esp-cred"); os.makedirs(M.ESP_CRED_DIR)
synced = []
_real_sync = os.sync
os.sync = lambda: synced.append(1)


def pl_calls():
    return open(pl_log).read().split() if os.path.exists(pl_log) else []


def ce_calls():
    return open(ce_log).read() if os.path.exists(ce_log) else ""


def reset_tpm():
    for fp in (pl_log, pl_mode, ce_log):
        if os.path.exists(fp):
            os.remove(fp)
    synced.clear()


def set_mode(m):
    open(pl_mode, "w").write(m)


# refresh-policy
reset_tpm(); M._ask = lambda p: "아니오"
rc, _, _ = run_sb_out(M.cmd_tpm_refresh_policy)
check("refresh-policy: 확인이 틀리면 pcrlock 을 부르지 않음", rc == 1 and pl_calls() == [], str(pl_calls()))
M._ask = lambda p: M.REFRESH_ACK
rc, _, _ = run_sb_out(M.cmd_tpm_refresh_policy)
check("refresh-policy: 확인 뒤 lock-secureboot-policy → lock-secureboot-authority → make-policy 순서", rc == 0 and pl_calls() == ["lock-secureboot-policy", "lock-secureboot-authority", "make-policy"], str(pl_calls()))
check("refresh-policy: 성공하면 sync(ESP 의 credential flush)", synced == [1], str(synced))
reset_tpm(); set_mode("nopcr7")
rc, _, err = run_sb_out(M.cmd_tpm_refresh_policy)
check("refresh-policy: 결과에 PCR 7 이 없으면 실패(종료 1)·원인(pcrphase 유닛) 안내", rc == 1 and "PCR 7" in err and "pcrphase" in err and "refresh-policy" in err, f"{rc} {err[:200]}")
reset_tpm(); set_mode("fail:lock-secureboot-policy")
rc, _, err = run_sb_out(M.cmd_tpm_refresh_policy)
check("refresh-policy: 첫 단계가 실패하면 make-policy 를 부르지 않고 종료 1", rc == 1 and pl_calls() == ["lock-secureboot-policy"] and "재부팅하지 마세요" in err, f"{rc} {pl_calls()}")
reset_tpm(); set_mode("fail:make-policy")
rc, _, _ = run_sb_out(M.cmd_tpm_refresh_policy)
check("refresh-policy: make-policy 실패는 종료 1·sync 안 함", rc == 1 and synced == [], f"{rc} {synced}")
check("refresh-policy: 알 수 없는 인자 거부(종료 2)", run_sb(M.cmd_tpm_refresh_policy, "--yes") == 2)
reset_tpm(); os.environ["NIXSEAL_PCRLOCK"] = os.path.join(fake, "없는-pcrlock")
rc, _, err = run_sb_out(M.cmd_tpm_refresh_policy)
check("refresh-policy: pcrlock 바이너리가 없으면 종료 1(예외로 죽지 않음)", rc == 1 and "systemd-pcrlock" in err, f"{rc} {err[:120]}")
os.environ["NIXSEAL_PCRLOCK"] = fake_pl

# dbx-update/dbx 와의 연결: TPM 슬롯이 있을 때만, 변경 뒤에 정책 갱신
_real_has_tpm = M._has_tpm_slot
M._has_tpm_slot = lambda dev=None: True
M._ask = lambda p: M.HOME_ACK
put("dbx", M.G_DB, b"\x22" * 10); open(fw_state, "w").write("x")
if os.path.exists(fw_log): os.remove(fw_log)
reset_tpm()
rc, out, _ = run_sb_out(M.cmd_sb_dbx_update)
check("dbx-update(TPM 있음): fwupdmgr update 뒤에 정책 갱신 3단계를 이어서 부름", rc == 0 and "update -y" in fw_calls() and pl_calls() == ["lock-secureboot-policy", "lock-secureboot-authority", "make-policy"], f"{rc} {pl_calls()}")
check("dbx-update(TPM 있음): 확인 문구가 「이어서 정책 갱신」을 알림", "정책을 이어서 갱신" in out, out[:300])
open(fw_state, "w").write("x"); os.remove(fw_log); reset_tpm(); set_mode("fail:make-policy")
rc, _, err = run_sb_out(M.cmd_sb_dbx_update)
check("dbx-update(TPM 있음): 변경은 됐는데 정책 갱신이 실패하면 종료 1·「재부팅하지 마세요」 안내", rc == 1 and "update -y" in fw_calls() and "재부팅하지 마세요" in err and "이미 적용" in err, f"{rc} {err[:200]}")
open(fw_state, "w").write("x"); os.remove(fw_log); reset_tpm()
M._ask = lambda p: "아니오"
rc, _, _ = run_sb_out(M.cmd_sb_dbx_update)
check("dbx-update(TPM 있음): 확인이 틀리면 update 도 pcrlock 도 부르지 않음", rc == 1 and "update -y" not in fw_calls() and pl_calls() == [], f"{pl_calls()}")
M._has_tpm_slot = lambda dev=None: False
M._ask = lambda p: M.HOME_ACK
open(fw_state, "w").write("x"); reset_tpm()
rc, out, _ = run_sb_out(M.cmd_sb_dbx_update)
check("dbx-update(TPM 없음): 정책 갱신을 부르지 않고 복구 암호 안내", rc == 0 and pl_calls() == [] and "복구 암호" in out, f"{pl_calls()}")
# sb dbx(빈 dbx 채우기)도 같은 연결
M._has_tpm_slot = lambda dev=None: True
os.remove(dbxp); reset_tpm()
rc, _, _ = run_sb_out(M.cmd_sb_dbx)
check("sb dbx(TPM 있음): dbx 를 채운 뒤 정책 갱신", rc == 0 and os.path.exists(dbxp) and pl_calls()[-1:] == ["make-policy"], f"{rc} {pl_calls()}")
os.remove(dbxp); reset_tpm(); set_mode("fail:make-policy")
rc, _, err = run_sb_out(M.cmd_sb_dbx)
check("sb dbx(TPM 있음): 정책 갱신 실패는 종료 1", rc == 1 and "재부팅하지 마세요" in err, f"{rc}")
M._has_tpm_slot = lambda dev=None: False
os.remove(dbxp); reset_tpm()
rc, _, _ = run_sb_out(M.cmd_sb_dbx)
check("sb dbx(TPM 없음): 정책 갱신을 부르지 않음", rc == 0 and pl_calls() == [], f"{pl_calls()}")
put("dbx", M.G_DB, b"\x22" * 10)

# enroll
dev_file = os.path.join(fake, "fakedev"); open(dev_file, "w").write("x")
reset_tpm(); M._ask = lambda p: "아니오"; M._has_tpm_slot = lambda dev=None: False
rc, _, _ = run_sb_out(M.cmd_tpm_enroll, dev_file)
check("enroll: 확인이 틀리면 정책도 슬롯도 건드리지 않음", rc == 1 and pl_calls() == [] and ce_calls() == "")
M._ask = lambda p: M.TRUST_ACK
rc, _, _ = run_sb_out(M.cmd_tpm_enroll, dev_file)
args = ce_calls().split()
check("enroll: 정책 갱신 → systemd-cryptenroll(--tpm2-pcrlock=<정책>·--tpm2-with-pin=yes·장치)", rc == 0 and pl_calls()[-1:] == ["make-policy"] and "--tpm2-with-pin=yes" in args and f"--tpm2-pcrlock={M.PCRLOCK_JSON}" in args and args[-1] == dev_file and "--wipe-slot=tpm2" not in args, f"{rc} {args}")
reset_tpm(); set_mode("nopcr7")
rc, _, _ = run_sb_out(M.cmd_tpm_enroll, dev_file)
check("enroll: 정책에 PCR 7 이 없으면 슬롯을 등록하지 않음", rc == 1 and ce_calls() == "", ce_calls())
reset_tpm(); M._has_tpm_slot = lambda dev=None: True
rc, _, err = run_sb_out(M.cmd_tpm_enroll, dev_file)
check("enroll: 이미 TPM2 슬롯이 있으면 --replace 없이는 거부", rc == 1 and ce_calls() == "" and "--replace" in err, f"{rc}")
rc, _, _ = run_sb_out(M.cmd_tpm_enroll, "--replace", dev_file)
check("enroll --replace: 기존 TPM2 슬롯을 지우고 다시 등록(--wipe-slot=tpm2)", rc == 0 and "--wipe-slot=tpm2" in ce_calls().split(), ce_calls())
check("enroll: 알 수 없는 옵션 거부(종료 2)", run_sb(M.cmd_tpm_enroll, "--force", dev_file) == 2)
M.CRYPTROOT = os.path.join(fake, "없는-cryptroot")
check("enroll: 장치를 못 찾으면 종료 2", run_sb(M.cmd_tpm_enroll) == 2)

# status
M._has_tpm_slot = lambda dev=None: True
rc, out, _ = run_sb_out(M.cmd_tpm_status, dev_file)
check("status: 정책 파일이 없으면 그렇게 말함", rc == 0 and "정책 파일: 없음" in out, out)
open(M.PCRLOCK_JSON, "w").write(json.dumps({"pcrValues": [{"pcr": 3, "values": ["a"]}, {"pcr": 15, "values": ["b"]}]}))
rc, out, _ = run_sb_out(M.cmd_tpm_status, dev_file)
check("status: PCR 7 이 정책에 없으면 경고", "[3, 15]" in out and "경고" in out and "PCR 7" in out, out)
open(M.PCRLOCK_JSON, "w").write(json.dumps({"pcrValues": [{"pcr": 7, "values": ["a"]}]}))
open(os.path.join(M.ESP_CRED_DIR, "pcrlock.abc.cred"), "w").write("x")
rc, out, _ = run_sb_out(M.cmd_tpm_status, dev_file)
check("status: PCR 7 이 있으면 경고 없음, ESP credential 수를 보여 줌", "경고" not in out and "1개" in out and "pcrlock.abc.cred" in out, out)
open(M.PCRLOCK_JSON, "w").write("깨진 json")
check("status: 깨진 정책 파일도 예외 없이 처리", run_sb_out(M.cmd_tpm_status, dev_file)[0] == 0)
check("_has_tpm_slot: 장치가 없으면 False(TPM 을 쓰지 않는 것으로 봄)", _real_has_tpm() is False and _real_has_tpm(os.path.join(fake, "없는-장치")) is False)
os.sync = _real_sync
M._has_tpm_slot = _real_has_tpm
shutil.rmtree(fake, ignore_errors=True)

if shutil.which("cryptsetup") is None:
    print("cryptsetup 없음 — 통합 시험 건너뜀")
    print(f"\nnixseal {n['ok']} 통과 / {n['bad']} 실패 (통합 건너뜀)")
    sys.exit(1 if n["bad"] else 0)

tmp = tempfile.mkdtemp()
img = os.path.join(tmp, "disk.img")
bak = os.path.join(tmp, "bak"); os.makedirs(bak)
PW = "test pass one two"
with open(img, "wb") as f:
    f.truncate(64 * 1024 * 1024)
r = subprocess.run(["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode", "--pbkdf", "pbkdf2", "--pbkdf-force-iterations", "1000", "--key-file=-", img],
                   input=PW.encode(), capture_output=True)
check("시험용 LUKS 이미지 생성", r.returncode == 0, r.stderr.decode())


NAMES = {"backup-header": "backup", "restore-header": "restore"}


def lc(*a, inp=None):
    return subprocess.run([sys.executable, "-I", LC, "luks", NAMES.get(a[0], a[0]), *a[1:]], capture_output=True, text=True, input=inp)


r = lc("backup-header", img, bak)
out = r.stdout.strip()
check("backup-header 성공", r.returncode == 0 and os.path.isfile(out), r.stderr)
uuid = subprocess.run(["cryptsetup", "luksUUID", img], capture_output=True, text=True).stdout.strip()
check("파일명에 UUID", uuid in os.path.basename(out))
check("권한 0400", stat.S_IMODE(os.stat(out).st_mode) == 0o400, oct(os.stat(out).st_mode))
check("슬롯 변경 시 재백업 안내", "다시 백업" in r.stderr)
r2 = lc("verify", out); check("verify(백업 파일)", r2.returncode == 0 and uuid in r2.stdout, r2.stderr)
check("verify: LUKS 아님 → 실패", lc("verify", os.path.join(tmp, "bak")).returncode != 0)
rs = lc("slots", img); check("slots: 1개", rs.returncode == 0 and "키슬롯 1개" in rs.stdout, rs.stdout + rs.stderr)
check("없는 대상 디렉터리 → 실패", lc("backup-header", img, os.path.join(tmp, "nope")).returncode != 0)

# 손상 → 복원 (장치 경로 확인 입력이 틀리면 변경 없음)
with open(img, "r+b") as f:
    f.write(b"\0" * (1024 * 1024))
check("손상 후 verify 실패", lc("verify", img).returncode != 0)
rbad = lc("restore-header", img, out, inp="wrong\n")
check("확인 입력 틀리면 중단·변경 없음", rbad.returncode != 0 and lc("verify", img).returncode != 0, rbad.stderr)
rok = lc("restore-header", img, out, inp=img + "\n")
check("restore-header 성공", rok.returncode == 0, rok.stdout + rok.stderr)
check("복원 후 verify 성공", lc("verify", img).returncode == 0)
t = subprocess.run(["cryptsetup", "open", "--test-passphrase", "--key-file=-", img], input=PW.encode(), capture_output=True)
check("복원 후 원래 암호로 열림", t.returncode == 0, t.stderr.decode())

# --name 은 경로·옵션 모양을 거부한다
for bad in ("../x", "a/b", "-x"):
    check(f"--name {bad!r} 거부", lc("backup-header", img, bak, "--name", bad).returncode == 2)

# 다른 장치(UUID 다름)의 백업을 덮으려면 추가 확인이 필요하다
img2 = os.path.join(tmp, "other.img"); open(img2, "wb").truncate(64 * 1024 * 1024)
subprocess.run(["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode", "--pbkdf", "pbkdf2", "--pbkdf-force-iterations", "1000", "--key-file=-", img2], input=b"other pw", check=True, capture_output=True)
u2 = subprocess.run(["cryptsetup", "luksUUID", img2], capture_output=True, text=True).stdout.strip()
rdiff = lc("restore-header", img2, out, inp=img2 + "\n")
check("UUID 다름: 경고 후 'overwrite' 없으면 중단·변경 없음", rdiff.returncode != 0 and "UUID 가 다릅니다" in rdiff.stdout and subprocess.run(["cryptsetup", "luksUUID", img2], capture_output=True, text=True).stdout.strip() == u2, rdiff.stdout + rdiff.stderr)
rdiff2 = lc("restore-header", img2, out, inp="overwrite\n" + img2 + "\n")
check("UUID 다름: overwrite + 경로 확인 뒤에는 복원", rdiff2.returncode == 0, rdiff2.stdout + rdiff2.stderr)

# ── reseal: 파일 이미지에서 전체 흐름·가드를 시험한다(root 불필요; 데이터 보존은 사람이 한 리허설 E3 로 확인: 해시 동일) ──
os.environ["NIXSEAL_PBKDF_FAST"] = "1"
import contextlib, io


def mk_img(path, pws=("old one",)):
    with open(path, "wb") as f:
        f.truncate(64 * 1024 * 1024)
    subprocess.run(["cryptsetup", "luksFormat", "--type", "luks2", "--batch-mode", "--pbkdf", "pbkdf2", "--pbkdf-force-iterations", "1000", "--key-file=-", path],
                   input=pws[0].encode(), check=True, capture_output=True)
    for extra in pws[1:]:
        r, w = os.pipe(); r2, w2 = os.pipe()
        os.write(w, pws[0].encode()); os.close(w); os.write(w2, extra.encode()); os.close(w2)
        subprocess.run(["cryptsetup", "luksAddKey", "--batch-mode", "--pbkdf", "pbkdf2", "--pbkdf-force-iterations", "1000", "--key-file", f"/dev/fd/{r}", path, f"/dev/fd/{r2}"],
                       pass_fds=(r, r2), check=True, capture_output=True)
        os.close(r); os.close(r2)


def opens(path, pw):
    return subprocess.run(["cryptsetup", "open", "--test-passphrase", "--key-file=-", path], input=pw.encode(), capture_output=True).returncode == 0


def nslots(path):
    return len(M.parse_slots(subprocess.run(["cryptsetup", "luksDump", path], capture_output=True, text=True).stdout)["slots"])


NEWPW = "alpha beta gamma delta epsilon zeta eta theta"


def run_reseal(img_path, bdir, secrets, asks, *extra):
    """secrets: _ask_secret 가 차례로 돌려줄 값, asks: _ask(Enter·경로 확인)가 돌려줄 값. (종료코드, 호출된 _ask 수)를 돌려준다."""
    sq, aq = list(secrets), list(asks)
    M._ask_secret = lambda p: sq.pop(0) if sq else ""
    M._ask = lambda p: aq.pop(0) if aq else ""
    M._clear_screen = lambda: None
    M._new_passphrase = lambda: NEWPW
    M._show_qr = lambda t: None
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            M.cmd_luks_reseal(["--backup-dir", bdir, "--force-offline", "--allow-tmpfs", *extra, img_path])
        return 0
    except SystemExit as e:
        return e.code or 0


M.POWER_SUPPLY_DIR = os.path.join(tmp, "no-power")  # 전원 정보 없음 → 통과(경고만)
if M._fstype(tmp) in ("tmpfs", "ramfs"):  # 이 시험 폴더가 RAM 디스크일 때만 확인할 수 있다
    ti = os.path.join(tmp, "t.img"); mk_img(ti)
    err = io.StringIO()
    M._ask_secret = lambda p: "wrong"; M._ask = lambda p: ""
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            M.cmd_luks_reseal(["--backup-dir", tmp, "--force-offline", ti])
        rc_t = 0
    except SystemExit as e:
        rc_t = e.code or 0
    check("reseal: RAM 디스크(tmpfs) 백업 디렉터리는 --allow-tmpfs 없이는 거부(그 이유로)", rc_t != 0 and "tmpfs" in err.getvalue(), err.getvalue()[-120:])
rb = os.path.join(tmp, "rb"); os.makedirs(rb)
ri = os.path.join(tmp, "r.img")

# 새 암호를 잘못 재입력 → 중단, 디스크 불변(슬롯 그대로·백업 안 만듦)
mk_img(ri, ("old one", "second"))
rc = run_reseal(ri, rb, ["old one", "x", "y", "z"], ["", M.BACKUP_ACK, ri, ri, ri])  # 경로 확인은 맞게 줘서 재입력 검사만이 막게 한다
check("reseal: 새 암호 재입력 3회 실패 → 중단·슬롯 불변·백업 없음", rc != 0 and nslots(ri) == 2 and opens(ri, "old one") and not os.listdir(rb), f"rc={rc} slots={nslots(ri)} {os.listdir(rb)}")
# 현재 암호를 모름 → 중단
rc = run_reseal(ri, rb, ["bad1", "bad2", "bad3"], [])
check("reseal: 현재 암호 3회 실패 → 중단·불변", rc != 0 and nslots(ri) == 2 and not os.listdir(rb))
# 장치 경로 확인이 틀림 → 중단, 슬롯·백업 불변
rc = run_reseal(ri, rb, ["old one", NEWPW], ["", "no", ri])
check("reseal: 백업 확인 문구가 틀리면 중단·슬롯 불변·백업 없음", rc != 0 and nslots(ri) == 2 and opens(ri, "old one") and not opens(ri, NEWPW) and not os.listdir(rb), f"rc={rc} slots={nslots(ri)} {os.listdir(rb)}")
rc = run_reseal(ri, rb, ["old one", NEWPW], ["", M.BACKUP_ACK, "wrong-path"])
check("reseal: 경로 확인 불일치 → 중단·슬롯 불변·백업 없음", rc != 0 and nslots(ri) == 2 and opens(ri, "old one") and not opens(ri, NEWPW) and not os.listdir(rb), f"rc={rc} slots={nslots(ri)} {os.listdir(rb)}")
# AC 가 없거나 배터리가 낮아도 막지 않는다(경고만) — 백업이 전제이므로 정전 대비는 차단 조건이 아니다. 경고 문구가 나오는지만 본다.
pdir = os.path.join(tmp, "power"); os.makedirs(os.path.join(pdir, "BAT0")); os.makedirs(os.path.join(pdir, "AC"))
open(os.path.join(pdir, "BAT0", "type"), "w").write("Battery\n"); open(os.path.join(pdir, "AC", "type"), "w").write("Mains\n"); open(os.path.join(pdir, "AC", "online"), "w").write("0\n")
open(os.path.join(pdir, "BAT0", "capacity"), "w").write("80\n")
M.POWER_SUPPLY_DIR = pdir
check("전원 판정: AC 없음·배터리만 → False", M._on_ac_power() is False)
open(os.path.join(pdir, "AC", "online"), "w").write("1\n")
check("전원 판정: AC 연결 → True, 배터리 잔량 읽기", M._on_ac_power() is True and M._battery_percent() == 80)
M.POWER_SUPPLY_DIR = os.path.join(tmp, "no-power")
# 실제 reencrypt 는 root 전용 락(/run/cryptsetup)이 필요하다 → 이 단계만 `sudo -n` 으로 실행하고, sudo 가 없으면 정상 흐름 시험은 건너뛴다
HAVE_SUDO = subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0
if HAVE_SUDO:
    real_cs = shutil.which("cryptsetup")
    sudo_cs = os.path.join(tmp, "sudo-cs.sh")
    with open(sudo_cs, "w") as f:
        f.write('#!/bin/sh\nexec sudo -n %s "$@"\n' % real_cs)
    os.chmod(sudo_cs, 0o755)
    _orig_re = M._run_reencrypt

    def _sudo_re(*a):
        old = M.CRYPTSETUP
        M.CRYPTSETUP = sudo_cs
        try:
            return _orig_re(*a)
        finally:
            M.CRYPTSETUP = old
    M._run_reencrypt = _sudo_re
# 정상 흐름: 새 암호만 남고 옛 암호·옛 슬롯은 사라지며 토큰도 정리되고, 백업은 하나만 남는다
tokj = os.path.join(tmp, "tok.json")
open(tokj, "w").write('{"type":"systemd-fido2","keyslots":["1"],"fido2-credential":"AA==","fido2-salt":"AA==","fido2-rp":"io.systemd.cryptsetup","fido2-clientPin-required":true,"fido2-up-required":true,"fido2-uv-required":false}')
subprocess.run(["cryptsetup", "token", "import", "--json-file", tokj, ri], check=True, capture_output=True, stdin=subprocess.DEVNULL)
if not HAVE_SUDO:
    print("  (sudo -n 없음 — reseal 정상 흐름 시험 건너뜀)")
else:
    rc = run_reseal(ri, rb, ["old one", NEWPW], ["", M.BACKUP_ACK, ri])
    toks = M.parse_slots(subprocess.run(["cryptsetup", "luksDump", ri], capture_output=True, text=True).stdout)["tokens"]
    left = os.listdir(rb)
    check("reseal: 정상 종료(rc 0)", rc == 0, f"rc={rc}")
    check("reseal: 슬롯 1개(새 암호만), 옛 암호는 안 열림", nslots(ri) == 1 and opens(ri, NEWPW) and not opens(ri, "old one") and not opens(ri, "second"), f"slots={nslots(ri)}")
    check("reseal: 옛 FIDO2 토큰 정리", toks == [], str(toks))
    check("reseal: 백업은 끝난 뒤 초기 상태 하나만(되돌림용은 삭제)", len(left) == 1 and left[0].startswith("luks-header-") and subprocess.run(["cryptsetup", "isLuks", os.path.join(rb, left[0])]).returncode == 0, str(left))
    check("reseal: 끝난 뒤 백업은 새 복구 암호로 열림", opens(os.path.join(rb, left[0]), NEWPW) if left else False)

# 실제 LUKS 이미지: systemd-tpm2 토큰이 있을 때만 _has_tpm_slot 이 True
ti = os.path.join(tmp, "tpmtok.img")
subprocess.run(["truncate", "-s", "20M", ti], check=True)
subprocess.run(["cryptsetup", "luksFormat", "-q", "--type", "luks2", "--pbkdf", "pbkdf2", "--pbkdf-force-iterations", "1000", "--key-file=-", ti], input=b"pw", check=True, capture_output=True)
check("_has_tpm_slot: 토큰이 없는 실제 LUKS 이미지는 False", _real_has_tpm(ti) is False)
tj = os.path.join(tmp, "tpmtok.json")
open(tj, "w").write('{"type":"systemd-tpm2","keyslots":["0"],"tpm2-blob":"AA==","tpm2-pcrs":[],"tpm2-pcr-bank":"sha256","tpm2-primary-alg":"ecc","tpm2-policy-hash":"AA==","tpm2-pin":true}')
subprocess.run(["cryptsetup", "token", "import", "--json-file", tj, ti], check=True, capture_output=True, stdin=subprocess.DEVNULL)
check("_has_tpm_slot: systemd-tpm2 토큰이 있으면 True", _real_has_tpm(ti) is True)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nnixseal {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
