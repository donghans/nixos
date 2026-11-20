#!/usr/bin/env python3
"""nixseal pw 시험 — 가짜 TPM(봉인 객체를 파일로 흉내)·가짜 계정 확인으로 봉인·해제·상태·삭제 흐름을 검증한다. root·TPM 불필요.
지키는 것: 「틀린 계정 비밀번호는 봉인하지 않고, 비밀(PIN·P)은 명령줄·출력·world-readable 파일에 나오지 않으며, 봉인한 값이 PIN 으로 풀릴 때만 저장한다」.
실행: python3 -I core/scripts/tests/test_nixseal_pw.py   (실제 TPM·부팅·greetd 에서의 동작은 VM 시험 core/scripts/tests/vm 의 `-A tpmlogin`)"""
import contextlib, hashlib, importlib.util, io, json, os, pwd, stat, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("nixseal", os.path.join(os.path.dirname(HERE), "nixseal.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
os.environ["NIXSEAL_NO_SUDO"] = "1"
n = {"ok": 0, "bad": 0}
ME = pwd.getpwuid(os.getuid()).pw_name
PIN, PW = "긴 PIN with 공백 123", "S3cure-Account-Pass!"


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


class World:
    def __init__(self, tpm_present=True, chkpwd=True):
        self.tmp = tempfile.mkdtemp()
        M.PWSEAL_DIR = os.path.join(self.tmp, "pwseal")
        M.TPMRM = os.path.join(self.tmp, "tpmrm0")
        if tpm_present:
            open(M.TPMRM, "w").close()
        self.calls = []        # (명령, 인자, stdin)
        self.chk = chkpwd
        self.objs = {}         # 봉인 객체(공개 파일 내용 → (인증값, 비밀))
        self.counter = 0
        self.unseal_override = None
        M._tpm = self.fake_tpm
        M._chkpwd = lambda user, pw: self.chk(pw) if callable(self.chk) else self.chk
        M._need_root = lambda args: None

    def fake_tpm(self, name, args, input_bytes=None):
        self.calls.append((name, list(args), input_bytes))
        ok = subprocess.CompletedProcess([name], 0, b"", b"")
        a = list(args)
        val = lambda flag: a[a.index(flag) + 1]
        if name in ("tpm2_createprimary", "tpm2_startauthsession", "tpm2_flushcontext"):
            return ok
        if name == "tpm2_create":
            secret = open(val("-i"), "rb").read().decode()
            tag = os.urandom(8).hex()
            open(val("-u"), "w").write(tag); open(val("-r"), "w").write(json.dumps({"auth": input_bytes.hex(), "secret": secret}))
            return ok
        if name == "tpm2_load":
            pub, priv = open(val("-u")).read(), json.loads(open(val("-r")).read())
            open(val("-c"), "w").write(json.dumps(priv))
            return ok
        if name == "tpm2_unseal":
            obj = json.loads(open(val("-c")).read())
            if self.unseal_override:
                return self.unseal_override
            if input_bytes.hex() != obj["auth"]:
                self.counter += 1
                return subprocess.CompletedProcess([name], 3, b"", b"ERROR: tpm:session(1):the authorization HMAC check failed and DA counter incremented")
            open(val("-o"), "w").write(obj["secret"])
            return ok
        return subprocess.CompletedProcess([name], 127, b"", b"unknown")


def run(fn, args, stdin="", secrets=()):
    out, err = io.StringIO(), io.StringIO()
    old_in = sys.stdin
    sys.stdin = io.StringIO(stdin)
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                fn(args)
            except SystemExit as e:
                code = e.code if isinstance(e.code, int) else 1
    finally:
        sys.stdin = old_in
    return code, out.getvalue(), err.getvalue()


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


# ── 인증값 도출 ──
check("인증값 = SHA-256(PIN) 32바이트(긴 PIN·한글·공백 가능)", M._pw_auth(PIN) == hashlib.sha256(PIN.encode()).digest() and len(M._pw_auth("x" * 300)) == 32)

# ── seal 성공 ──
w = World(chkpwd=lambda pw: pw == PW)
code, out, err = run(M.cmd_pw_seal, ["--user", ME, "--stdin"], stdin=f"{PIN}\n{PW}\n")
pub, priv, failed = M._pw_paths(ME)
check("seal --stdin 성공(종료 0)", code == 0, out + err)
check("블롭 파일이 만들어졌고 0600, 디렉터리 0700", os.path.exists(pub) and os.path.exists(priv) and mode(pub) == 0o600 and mode(priv) == 0o600 and mode(M.PWSEAL_DIR) == 0o700)
argv_all = " ".join(" ".join(c[1]) for c in w.calls)
check("비밀(PIN·P)이 어떤 명령줄 인자에도 없다", PIN not in argv_all and PW not in argv_all, argv_all)
create = [c for c in w.calls if c[0] == "tpm2_create"][0]
check("봉인은 기본 속성(DA 켜짐)으로 — -a 를 주지 않는다", "-a" not in create[1])
check("봉인 인증값은 stdin(-p file:-)으로 SHA-256(PIN)", "file:-" in create[1] and create[2] == hashlib.sha256(PIN.encode()).digest())
check("봉인 직후 풀어 확인한다(load·unseal 호출)", any(c[0] == "tpm2_load" for c in w.calls) and any(c[0] == "tpm2_unseal" for c in w.calls))
check("출력에 PIN·P 가 나오지 않는다", PIN not in out + err and PW not in out + err)
check("임시 작업 폴더가 남지 않는다", not [d for d in os.listdir("/run") if d.startswith("nixseal-pw.")] if os.path.isdir("/run") else True)

# ── 입력 검증: 아무 것도 저장하지 않는 경우 ──
for name, kw, stdin, args, word in [
    ("틀린 계정 비밀번호", dict(chkpwd=lambda pw: False), f"{PIN}\n{PW}\n", ["--user", ME, "--stdin"], "현재 비밀번호와 다르다"),
    ("확인 수단 없음", dict(chkpwd=None), f"{PIN}\n{PW}\n", ["--user", ME, "--stdin"], "확인할 수단"),
    ("빈 PIN", dict(chkpwd=True), f"\n{PW}\n", ["--user", ME, "--stdin"], "비어 있을 수 없다"),
    ("빈 비밀번호", dict(chkpwd=True), f"{PIN}\n\n", ["--user", ME, "--stdin"], "비어 있을 수 없다"),
    ("TPM 장치 없음", dict(chkpwd=True, tpm_present=False), f"{PIN}\n{PW}\n", ["--user", ME, "--stdin"], "TPM 장치"),
]:
    w = World(**kw)
    code, out, err = run(M.cmd_pw_seal, args, stdin=stdin)
    check(f"{name} → 거부(종료 비0)·메시지", code != 0 and word in err, err)
    check(f"{name} → 아무 것도 저장하지 않고 TPM 에 봉인하지 않는다", not os.path.exists(M._pw_paths(ME)[0]) and not any(c[0] == "tpm2_create" for c in w.calls))
w = World(chkpwd=True)
M._ask_secret = lambda prompt: {"TPM": PIN, "비밀번호": PW}.get([k for k in ("TPM", "비밀번호") if k in prompt][0] if any(k in prompt for k in ("TPM", "비밀번호")) else "", "다름" if "한 번 더" in prompt else "")
seq = iter([PIN, PW, "다른 값"])
M._ask_secret = lambda prompt: next(seq)
code, out, err = run(M.cmd_pw_seal, ["--user", ME])
check("대화형: 계정 비밀번호 확인 입력이 다르면 중단", code != 0 and "다르다" in err and not os.path.exists(M._pw_paths(ME)[0]), err)

# ── 봉인한 값이 풀리지 않으면 저장하지 않는다 ──
w = World(chkpwd=True)
w.unseal_override = subprocess.CompletedProcess(["tpm2_unseal"], 1, b"", b"ERROR: something")
code, out, err = run(M.cmd_pw_seal, ["--user", ME, "--stdin"], stdin=f"{PIN}\n{PW}\n")
check("봉인 직후 풀기가 실패하면 저장하지 않는다", code != 0 and "저장하지 않았다" in err and not os.path.exists(M._pw_paths(ME)[0]), err)

# ── 재봉인: 실패 표지를 지운다 / 교체 확인 ──
w = World(chkpwd=lambda pw: pw == PW)
run(M.cmd_pw_seal, ["--user", ME, "--stdin"], stdin=f"{PIN}\n{PW}\n")
open(M._pw_paths(ME)[2], "w").write("bad-pin 2026-01-01\n")
run(M.cmd_pw_seal, ["--user", ME, "--stdin"], stdin=f"{PIN}\n{PW}\n")
check("재봉인은 실패 표지를 지운다", not os.path.exists(M._pw_paths(ME)[2]))
before = open(M._pw_paths(ME)[1]).read()
M._ask = lambda prompt: "아니오"
seq = iter([PIN, PW, PW])
M._ask_secret = lambda prompt: next(seq)
code, out, err = run(M.cmd_pw_seal, ["--user", ME])
check("이미 봉인이 있을 때 교체 확인을 하지 않으면 취소(블롭 그대로)", code != 0 and open(M._pw_paths(ME)[1]).read() == before)

# ── test: 풀기·계정 비밀번호 확인 ──
M._ask_secret = lambda prompt: PIN
code, out, err = run(M.cmd_pw_test, ["--user", ME])
check("test: 맞는 PIN → 정상 메시지, 비밀번호는 출력하지 않는다", code == 0 and "정상" in out and PW not in out + err, out + err)
M._ask_secret = lambda prompt: "틀린 PIN"
before_counter = w.counter
code, out, err = run(M.cmd_pw_test, ["--user", ME])
check("test: 틀린 PIN → 오입력 카운터 안내", code != 0 and "카운터" in err and w.counter == before_counter + 1, err)
w.unseal_override = subprocess.CompletedProcess(["tpm2_unseal"], 1, b"", b"ERROR: authorizations for objects subject to DA protection are not allowed at this time because the TPM is in DA lockout mode")
M._ask_secret = lambda prompt: PIN
code, out, err = run(M.cmd_pw_test, ["--user", ME])
check("test: 잠금 상태 → 잠금 안내", code != 0 and "잠금" in err, err)
w.unseal_override = None
w.chk = lambda pw: False
code, out, err = run(M.cmd_pw_test, ["--user", ME])
check("test: 풀렸지만 계정 비밀번호와 다르면(stale) 재봉인 안내", code != 0 and "다시" in err or "nixseal pw seal" in err, err)
w.chk = True

# ── status ──
open(M._pw_paths(ME)[2], "w").write("bad-pin 2026-01-01T00:00:00\n")
code, out, err = run(M.cmd_pw_status, ["--user", ME])
check("status: bad-pin 표지 설명과 할 일", "bad-pin" in out and "nixseal pw seal" in out and "카운터" in out, out)
open(M._pw_paths(ME)[2], "w").write("stale 2026-01-01T00:00:00\n")
code, out, err = run(M.cmd_pw_status, ["--user", ME])
check("status: stale 표지 설명", "stale" in out and "계정 비밀번호" in out, out)

# ── remove ──
M._ask = lambda prompt: "아니오"
code, out, err = run(M.cmd_pw_remove, ["--user", ME])
check("remove: 확인 문구가 다르면 취소(파일 그대로)", code != 0 and os.path.exists(M._pw_paths(ME)[0]))
code, out, err = run(M.cmd_pw_remove, ["--user", ME, "--yes"])
check("remove --yes: 블롭·표지 삭제 + 계정 비밀번호는 그대로라는 안내", not os.path.exists(M._pw_paths(ME)[0]) and not os.path.exists(M._pw_paths(ME)[2]) and "직접 입력" in out, out)
code, out, err = run(M.cmd_pw_remove, ["--user", ME, "--yes"])
check("remove: 이미 없으면 지울 것이 없다고 말하고 성공", code == 0 and "없다" in out)

# ── 계정 결정 ──
for k in ("NIXSEAL_DECL_TPMLOGIN", "SUDO_USER"):
    os.environ.pop(k, None)
code, out, err = run(M.cmd_pw_status, [])
check("계정을 정할 수 없으면 거부", code == 2 and "--user" in err, err)
code, out, err = run(M.cmd_pw_status, ["--user", "root"])
check("root 는 거부", code == 2, err)
code, out, err = run(M.cmd_pw_status, ["--user", "no-such-user-xyz"])
check("없는 계정은 거부", code == 2 and "없다" in err, err)
os.environ["NIXSEAL_DECL_TPMLOGIN"] = ME
check("nix 선언(NIXSEAL_DECL_TPMLOGIN)이 기본 계정", M._pw_user([]) == ME)

print(f"nixseal-pw {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
