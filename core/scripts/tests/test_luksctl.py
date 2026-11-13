#!/usr/bin/env python3
"""luksctl 시험 — 실제 cryptsetup 으로 일반 파일 이미지(root 불필요)에서 백업→손상→복원을 돌린다.
cryptsetup 이 PATH 에 없으면 건너뜀(종료 0). 실행: nix shell nixpkgs#cryptsetup -c python3 -I core/scripts/tests/test_luksctl.py"""
import importlib.util, os, shutil, stat, subprocess, sys, tempfile

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LC = os.path.join(SCRIPTS, "luksctl.py")
n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


spec = importlib.util.spec_from_file_location("luksctl", LC)
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

if shutil.which("cryptsetup") is None:
    print("cryptsetup 없음 — 통합 시험 건너뜀")
    print(f"\nluksctl {n['ok']} 통과 / {n['bad']} 실패 (통합 건너뜀)")
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


def lc(*a, inp=None):
    return subprocess.run([sys.executable, "-I", LC, *a], capture_output=True, text=True, input=inp)


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

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nluksctl {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
