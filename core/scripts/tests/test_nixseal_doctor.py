#!/usr/bin/env python3
"""nixseal doctor 시험 — 선언(nix)과 실제 상태의 어긋남 판정. root·디스크·TPM 불필요(판정은 순수 함수, 사실 수집은 가짜 명령으로).
지키는 것: 「위험한 상태(다음 부팅이 깨지거나 보호가 조용히 빠진 상태)를 OK 로 보고하지 않는다」, 「모르는 칸은 정상이 아니라 건너뜀/INFO 로 보고한다」.
실행: python3 -I core/scripts/tests/test_nixseal_doctor.py   (실제 장치·TPM·펌웨어에서의 사실 수집은 VM 시험 core/scripts/tests/vm 의 `-A doctor`)"""
import contextlib, importlib.util, io, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("nixseal", os.path.join(os.path.dirname(HERE), "nixseal.py"))
M = importlib.util.module_from_spec(spec); spec.loader.exec_module(M)
os.environ["NIXSEAL_NO_SUDO"] = "1"
n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


def facts(**kw):
    """정상(암호화 루트·TPM 슬롯·PCR 7 정책·credential·SB 켜짐) 사실에서 일부만 바꾼다."""
    f = dict(root_src="/dev/mapper/cryptroot", root_crypt=True, sb_on=1, setup_mode=0, tokens={"systemd-tpm2", "systemd-fido2"},
             policy_pcrs=[3, 7, 13], creds=1, luks_dev="/dev/x", policy_exists=True, fp_now="aa", fp_saved="aa", is_root=True)
    f.update(kw)
    return f


def decl(**kw):
    d = dict(sb=True, tpm2=True, fido2=False, luks="cryptroot", luks_dev="/dev/x")
    d.update(kw)
    return d


def sevs(d, f):
    return [s for s, _ in M._judge(d, f)]


def has(d, f, sev, word=""):
    return any(s == sev and word in m for s, m in M._judge(d, f))


# ── 정상 ──
r = M._judge(decl(), facts())
check("정상: FAIL·WARN 없음", not [s for s, _ in r if s in ("FAIL", "WARN")], str(r))
check("정상: OK 가 있다(아무 말도 안 하는 것과 구분)", any(s == "OK" for s, _ in r))

# ── LUKS 루트 ──
check("luks 선언 + 루트 평문 → FAIL", has(decl(), facts(root_src="/dev/disk/by-label/nixos", root_crypt=False), "FAIL", "부팅이 안 된다"))
check("luks 선언 없음(\"\") + 루트 암호화 → FAIL", has(decl(luks="", tpm2=False), facts(), "FAIL", "crypttab"))
r = M._judge(decl(luks="", tpm2=False), facts(root_src="/dev/sda2", root_crypt=False, tokens=None))
check("luks 선언 없음 + 평문 → OK(FAIL·WARN 없음)", any(s == "OK" and "luks 선언 없음" in m for s, m in r) and not [s for s, _ in r if s in ("FAIL", "WARN")], str(r))
check("luks 모름(None) → 암호화 칸은 판정하지 않는다", not has(decl(luks=None), facts(root_crypt=False, root_src="/dev/sda2"), "FAIL"))
check("루트를 못 읽음 → FAIL 이 아니라 INFO", has(decl(), facts(root_src=None, root_crypt=None), "INFO", "확인하지 못했다") and not has(decl(), facts(root_src=None, root_crypt=None), "FAIL"))

# ── TPM2 슬롯·정책 ──
check("tpm2 선언 + 슬롯 없음 → INFO(등록 안내)", has(decl(), facts(tokens=set()), "INFO", "nixseal tpm enroll") and not has(decl(), facts(tokens=set()), "FAIL"))
check("tpm2 미선언 + 슬롯 있음 → WARN", has(decl(tpm2=False), facts(), "WARN", "쓰이지 않는다"))
check("슬롯 있고 정책 파일 없음 → FAIL", has(decl(), facts(policy_pcrs=None), "FAIL", "정책 파일"))
check("슬롯 있고 정책에 PCR 7 없음 → FAIL(조용한 약화)", has(decl(), facts(policy_pcrs=[3, 13]), "FAIL", "PCR 7"))
check("슬롯 있고 ESP credential 없음 → FAIL", has(decl(), facts(creds=0), "FAIL", "credential"))
check("정책 PCR 7 + credential → OK", has(decl(), facts(), "OK", "PCR 7"))
check("정책 파일이 PCR 7 만 있어도 OK", not has(decl(), facts(policy_pcrs=[7]), "FAIL"))
check("tpm2 미선언 + 슬롯 없음 → OK", has(decl(tpm2=False), facts(tokens=set()), "OK", "슬롯도 없음"))
check("헤더를 못 읽음 → INFO(슬롯 판정 안 함, FAIL 아님)", has(decl(), facts(tokens=None), "INFO", "확인하지 못했다") and not has(decl(), facts(tokens=None), "FAIL"))
check("luks 없음 선언이면 슬롯 칸을 건너뛴다", not any("슬롯" in m for _, m in M._judge(decl(luks="", tpm2=True), facts(root_crypt=False, root_src="/dev/sda2", tokens=set()))))

# ── FIDO2 ──
check("fido2 선언 + 슬롯 없음 → INFO", has(decl(fido2=True, tpm2=False), facts(tokens=set()), "INFO", "FIDO2 슬롯이 없다"))
check("fido2 미선언 + 슬롯 있음 → INFO(의도일 수 있음, 경고 아님)", has(decl(fido2=False, tpm2=False), facts(tokens={"systemd-fido2"}, policy_exists=False), "INFO", "ISO") and not has(decl(fido2=False, tpm2=False), facts(tokens={"systemd-fido2"}, policy_exists=False), "WARN"))
check("tpm2·fido2 동시 선언 → WARN(우회)", has(decl(fido2=True), facts(), "WARN", "우회"))

# ── Secure Boot ──
check("sb 선언 + 펌웨어 꺼짐 → WARN", has(decl(), facts(sb_on=0), "WARN", "꺼져 있다"))
check("sb 선언 + Setup Mode → WARN", has(decl(), facts(setup_mode=1), "WARN", "Setup Mode"))
check("sb 선언 + 켜짐/User Mode → OK", has(decl(), facts(), "OK", "User Mode"))
check("sb 미선언(False) + 펌웨어 켜짐 → FAIL", has(decl(sb=False), facts(), "FAIL", "Access Denied"))
check("sb 미선언 + 꺼짐 → OK", has(decl(sb=False), facts(sb_on=0), "OK") and not has(decl(sb=False), facts(sb_on=0), "FAIL"))
check("sb 모름(None) → 판정하지 않는다", not any("펌웨어" in m or "secure-boot" in m for _, m in M._judge(decl(sb=None), facts(sb_on=1))))
check("펌웨어 변수를 못 읽음 → INFO", has(decl(), facts(sb_on=None, setup_mode=None), "INFO", "읽지 못했다"))

# ── 선언 환경변수(3값) ──
saved = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith("NIXSEAL_DECL_")}
try:
    d = M._decl()
    check("환경변수 없음 → 전부 None(모름)", all(v is None for v in d.values()), str(d))
    os.environ["NIXSEAL_DECL_LUKS"] = ""
    check("LUKS 빈 값 = 「luks 없음」 선언(None 과 구분)", M._decl()["luks"] == "")
    os.environ.update(NIXSEAL_DECL_LUKS="cryptroot", NIXSEAL_DECL_TPM2="1", NIXSEAL_DECL_FIDO2="0", NIXSEAL_DECL_SB="1", NIXSEAL_DECL_LUKS_DEV="/dev/disk/by-partlabel/cryptroot")
    d = M._decl()
    check("값 파싱", d == dict(sb=True, tpm2=True, fido2=False, luks="cryptroot", luks_dev="/dev/disk/by-partlabel/cryptroot", tplogin=None), str(d))
finally:
    for k in [k for k in os.environ if k.startswith("NIXSEAL_DECL_")]:
        del os.environ[k]
    os.environ.update(saved)

# ── 사실 수집(가짜 외부 명령·파일) ──
import tempfile
tmp = tempfile.mkdtemp()
calls = []


def fake_x(name, args, capture=True, input_text=None):
    calls.append((name, tuple(args)))
    if name == "findmnt":
        return subprocess.CompletedProcess([name], 0, "/dev/mapper/cryptroot\n", "")
    return subprocess.CompletedProcess([name], 127, "", "")


DUMP = b"LUKS header information\nKeyslots:\n  0: luks2\n\tKey: 512 bits\n\tPBKDF:      argon2id\nTokens:\n  0: systemd-tpm2\n  1: systemd-fido2\nDigests:\n  0: pbkdf2\n"
M._x = fake_x
M._dm_is_crypt = lambda src: src == "/dev/mapper/cryptroot"
M._cs = lambda a, input_bytes=None: subprocess.CompletedProcess(["cryptsetup"], 0, DUMP, b"")
M._luks_dev = lambda args: ""
M._pcrlock_pcrs = lambda: [3, 7]
M._esp_credentials = lambda: ["/boot/loader/credentials/pcrlock.x.cred"]
M.PCRLOCK_JSON = "/nonexistent-pcrlock.json"
M.var_byte = lambda name, guid: {"SecureBoot": 1, "SetupMode": 0}[name]
dv = os.path.join(tmp, "dev"); open(dv, "w").close()
M._sb_fingerprint = lambda: "fp-now"
M.FP_FILE = os.path.join(tmp, "sb-fingerprint"); open(M.FP_FILE, "w").write("fp-now\n")
M.ESP_MNT = tmp; M.ESP_CRED_DIR = tmp
f = M._gather_facts({"luks_dev": dv})
check("수집: 루트 매퍼·암호화 확인", f["root_src"] == "/dev/mapper/cryptroot" and f["root_crypt"] is True, str(f))
check("수집: findmnt 에 --nofsroot", ("findmnt", ("-no", "SOURCE", "--nofsroot", "/")) in calls)
check("수집: 토큰 종류", f["tokens"] == {"systemd-tpm2", "systemd-fido2"}, str(f["tokens"]))
check("수집: 정책 PCR·credential·SB", f["policy_pcrs"] == [3, 7] and f["creds"] == 1 and f["sb_on"] == 1 and f["setup_mode"] == 0)
check("수집: 지문(현재·기록)", f["fp_now"] == "fp-now" and f["fp_saved"] == "fp-now")
check("수집한 정상 사실 + 정상 선언 → FAIL·WARN 없음", not [s for s, _ in M._judge(decl(luks_dev=dv), f) if s in ("FAIL", "WARN")])
M._cs = lambda a, input_bytes=None: subprocess.CompletedProcess(["cryptsetup"], 1, b"", b"err")
check("수집: luksDump 실패 → tokens None(정상이 아님)", M._gather_facts({"luks_dev": dv})["tokens"] is None)
M._x = lambda name, args, capture=True, input_text=None: subprocess.CompletedProcess([name], 0, "/dev/nvme0n1p2\n", "") if name == "findmnt" else subprocess.CompletedProcess([name], 1, "", "")
f = M._gather_facts({"luks_dev": dv})
check("수집: 매퍼가 아닌 루트 → root_crypt False", f["root_src"] == "/dev/nvme0n1p2" and f["root_crypt"] is False)
M._x = lambda name, args, capture=True, input_text=None: subprocess.CompletedProcess([name], 0, "/dev/mapper/vg-root\n", "") if name == "findmnt" else subprocess.CompletedProcess([name], 1, "", "no such")
f = M._gather_facts({"luks_dev": dv})
check("수집: LVM 같은 비-crypt 매퍼 → root_crypt False(오탐 방지)", f["root_crypt"] is False)
M._dm_is_crypt = lambda src: None
f = M._gather_facts({"luks_dev": dv})
check("수집: sysfs 를 못 읽음 → root_crypt None, 판정은 FAIL 이 아니라 INFO", f["root_crypt"] is None and has(decl(), f, "INFO", "확인하지 못했다") and not has(decl(), f, "FAIL"))

# ── _dm_is_crypt 자체(가짜 sysfs): 실제 파일 경로 규칙을 읽는다 ──
import builtins
real_open, real_realpath = builtins.open, os.path.realpath
M2 = M
def fake_open(path, *a, **k):
    if str(path).startswith("/sys/class/block/"):
        uu = {"dm-0": "CRYPT-LUKS2-aaaa-cryptroot", "dm-1": "LVM-bbbb"}.get(str(path).split("/")[4])
        if uu is None: raise FileNotFoundError(path)
        return io.StringIO(uu)
    return real_open(path, *a, **k)
builtins.open = fake_open
os.path.realpath = lambda p: {"/dev/mapper/cryptroot": "/dev/dm-0", "/dev/mapper/vg-root": "/dev/dm-1", "/dev/mapper/ghost": "/dev/dm-9"}.get(p, p)
try:
    importlib.reload(sys.modules.get("nixseal")) if "nixseal" in sys.modules else None
    spec2 = importlib.util.spec_from_file_location("nixseal2", os.path.join(os.path.dirname(HERE), "nixseal.py"))
    N2 = importlib.util.module_from_spec(spec2); spec2.loader.exec_module(N2)
    check("_dm_is_crypt: CRYPT- 접두 → True", N2._dm_is_crypt("/dev/mapper/cryptroot") is True)
    check("_dm_is_crypt: LVM → False", N2._dm_is_crypt("/dev/mapper/vg-root") is False)
    check("_dm_is_crypt: 매퍼 아님 → False", N2._dm_is_crypt("/dev/nvme0n1p2") is False)
    check("_dm_is_crypt: sysfs 없음 → None", N2._dm_is_crypt("/dev/mapper/ghost") is None)
finally:
    builtins.open, os.path.realpath = real_open, real_realpath

# ── 정책 갱신이 지문을 남긴다(doctor 의 「갱신 누락」 검사의 전제) ──
real_run = M.subprocess.run
def fake_run_factory(mask_has7):
    def fake_run(cmd, *a, **k):
        out = "PCRs in protection mask: " + ("7 (secure-boot-policy)" if mask_has7 else "15 (system-identity)") + "\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")
    return fake_run
fp_keep, fn_keep = M.FP_FILE, M._sb_fingerprint
M._sb_fingerprint = lambda: "fp-after-refresh"
M.FP_FILE = os.path.join(tmp, "fp-written"); M.os.sync = lambda: None
M.subprocess.run = fake_run_factory(True)
ok = M._pcrlock_refresh()
check("정책 갱신 성공 → 그 시점의 지문이 기록된다", ok and open(M.FP_FILE).read().strip() == "fp-after-refresh")
os.remove(M.FP_FILE)
M.subprocess.run = fake_run_factory(False)
ok = M._pcrlock_refresh()
check("PCR 7 이 빠진 정책(실패)은 지문을 기록하지 않는다", (not ok) and not os.path.exists(M.FP_FILE))
M.subprocess.run = real_run
M.FP_FILE, M._sb_fingerprint = fp_keep, fn_keep

# ── 정책 갱신의 이전 상태 변종(dbx 를 바꾼 직후 재부팅 전 갱신에서도 PCR 7 이 남게) ──
vt = tempfile.mkdtemp()
D = os.path.join(vt, "240-secureboot-policy.pcrlock.d"); os.makedirs(D)
M.PCRLOCK_D = vt
M.BOOT_ID_FILE = os.path.join(vt, "boot_id"); M.VARIANT_BOOT_FILE = os.path.join(vt, "variants-boot")
M._sb_fingerprint = lambda: "fp"; M.FP_FILE = os.path.join(vt, "fp")
state = {"vars": b"STATE-A", "boot": "boot-1"}
def sim_run(cmd, *a, **k):
    sub = cmd[1]
    if sub == "lock-secureboot-policy":
        open(os.path.join(D, "generated.pcrlock"), "wb").write(state["vars"])
    out = "PCRs in protection mask: 7 (secure-boot-policy)\n" if sub == "make-policy" else ""
    return subprocess.CompletedProcess(cmd, 0, out, "")
M.subprocess.run = sim_run
def refresh():
    open(M.BOOT_ID_FILE, "w").write(state["boot"] + "\n")
    return M._pcrlock_refresh()
def variants():
    return sorted(f for f in os.listdir(D) if f.startswith("old-"))
import hashlib as _h
vA = "old-" + _h.sha256(b"STATE-A").hexdigest()[:12] + ".pcrlock"
vB = "old-" + _h.sha256(b"STATE-B").hexdigest()[:12] + ".pcrlock"
check("변종: 처음 만들 때는 변종이 없다", refresh() and variants() == [])
state["vars"] = b"STATE-B"                      # 같은 부팅에서 dbx 등을 바꿨다
check("변종: 바꾼 직후(재부팅 전) 갱신 → 바꾸기 전 상태가 변종으로 남는다", refresh() and variants() == [vA] and open(os.path.join(D, vA), "rb").read() == b"STATE-A")
check("변종: 같은 부팅의 두 번째 갱신은 변종을 지우지 않는다(로그는 아직 옛 상태)", refresh() and variants() == [vA])
state["boot"] = "boot-2"                        # 재부팅 — 이제 로그는 새 상태(B)
check("변종: 재부팅 뒤 첫 갱신은 옛 변종을 지운다(옛 상태를 영구히 허용하지 않는다)", refresh() and variants() == [])
state["vars"] = b"STATE-C"                      # 한 부팅 안에서 두 번 바꿈: B→C
check("변종: 재부팅 뒤 다시 바꿔 갱신 → B 가 변종", refresh() and variants() == [vB])
state["vars"] = b"STATE-D"
refresh()
check("변종: 갱신 전에 두 번 바꿔도 이전 상태들이 모두 변종으로 남는다(로그와 맞는 상태가 사라지지 않게)", len(variants()) == 2 and vB in variants())
# 실패 경로: PCR 7 이 빠지면 이 갱신은 실패로 보고되고 지문을 기록하지 않는다
M.subprocess.run = lambda cmd, *a, **k: subprocess.CompletedProcess(cmd, 0, "PCRs in protection mask: 15 (system-identity)\n" if cmd[1] == "make-policy" else "", "")
buf_e = io.StringIO()
with contextlib.redirect_stderr(buf_e):
    ok_missing = M._pcrlock_refresh()
check("PCR 7 이 빠지면 실패 + 두 원인(유닛·바꾼 뒤 변종 없음)을 안내", (not ok_missing) and "원인 ①" in buf_e.getvalue() and "원인 ②" in buf_e.getvalue())
M.subprocess.run = real_run
M._sb_fingerprint, M.FP_FILE = fn_keep, fp_keep

# ── 새 검사 ──
check("지문 불일치 → FAIL(정책 갱신 누락) + 재부팅 전 refresh-policy 안내", has(decl(), facts(fp_now="bb"), "FAIL", "바뀌었다") and has(decl(), facts(fp_now="bb"), "FAIL", "재부팅 전에"))
check("지문 일치 → 정상(FAIL·WARN 없음)", not [s for s, _ in M._judge(decl(), facts()) if s in ("FAIL", "WARN")])
check("지문 기록 없음 → INFO(확인 못함, FAIL 아님)", has(decl(), facts(fp_saved=None), "INFO", "기록돼 있지 않아") and not has(decl(), facts(fp_saved=None), "FAIL"))
check("현재 지문을 못 읽음 → INFO", has(decl(), facts(fp_now=None), "INFO", "읽지 못해") and not has(decl(), facts(fp_now=None), "FAIL"))
check("ESP 미마운트(creds None) → INFO(mount), FAIL 아님", has(decl(), facts(creds=None), "INFO", "마운트") and not has(decl(), facts(creds=None), "FAIL"))
check("정책 파일만 남고 슬롯 없음 → WARN(remove-policy)", has(decl(), facts(tokens=set()), "WARN", "remove-policy") or has(decl(), facts(tokens=set()), "WARN", "정책(NV"))
check("슬롯도 정책도 없으면 정책 경고 없음", not has(decl(), facts(tokens=set(), policy_exists=False), "WARN"))
check("LUKS 장치 모호(luks_dev None) → INFO 에 nix 위치", has(decl(), facts(tokens=None, luks_dev=None), "INFO", "둘 이상") and any("mods.sys.services.luks.device" in m for _, m in M._judge(decl(), facts(tokens=None, luks_dev=None))))
check("비루트로 헤더를 못 읽으면 sudo 안내", any("sudo nixseal doctor" in m for _, m in M._judge(decl(), facts(tokens=None, is_root=False))))

# ── 형식 강제: 모든 FAIL·WARN 은 「→ 할 일:」, INFO 는 「→ 할 일:」 또는 「→ nix:」 를 가진다(조합 전수) ──
import itertools
bad = []
n_msgs = 0
for lk, tp, fd, sbd in itertools.product([None, "", "cryptroot"], [None, True, False], [None, True, False], [None, True, False]):
    d = dict(sb=sbd, tpm2=tp, fido2=fd, luks=lk, luks_dev="/dev/x")
    for rc, rs in [(True, "/dev/mapper/cryptroot"), (False, "/dev/sda2"), (None, None)]:
        for tokens in [None, set(), {"systemd-tpm2"}, {"systemd-tpm2", "systemd-fido2"}, {"systemd-fido2"}]:
            for pcrs, creds, fp in [([3, 7], 1, "aa"), (None, 1, "aa"), ([3], 1, "aa"), ([7], 0, "aa"), ([7], None, "aa"), ([7], 1, "bb"), ([7], 1, None)]:
                for sb_on, sm in [(1, 0), (0, 0), (1, 1), (None, None)]:
                    for is_root, ldev, pe in [(True, "/dev/x", True), (False, None, False)]:
                        f = facts(root_src=rs, root_crypt=rc, tokens=tokens, policy_pcrs=pcrs, creds=creds, fp_now="aa", fp_saved=fp, sb_on=sb_on, setup_mode=sm, is_root=is_root, luks_dev=ldev, policy_exists=pe)
                        for sev, msg in M._judge(d, f):
                            n_msgs += 1
                            if sev in ("FAIL", "WARN") and "→ 할 일:" not in msg: bad.append((sev, msg[:60]))
                            if sev == "INFO" and "→ 할 일:" not in msg and "→ nix:" not in msg: bad.append((sev, msg[:60]))
check("형식 강제: 모든 FAIL·WARN·INFO 에 할 일/nix 위치가 있다(%d 건 점검)" % n_msgs, not bad and n_msgs > 1000, str(bad[:3]))

# ── cmd_doctor: 종료 코드·출력 ──
def run_doctor(env, args=()):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = M.cmd_doctor(list(args))
        return rc, buf.getvalue()
    finally:
        for k, v in old.items():
            if v is None: os.environ.pop(k, None)
            else: os.environ[k] = v


M._x = fake_x
M._dm_is_crypt = lambda src: src == "/dev/mapper/cryptroot"
M._esp_credentials = lambda: ["/boot/loader/credentials/pcrlock.x.cred"]
DUMP_TPM = DUMP.replace(b"  1: systemd-fido2\n", b"")  # fido2 선언을 끈 정상 상태(TPM 토큰만)
M._cs = lambda a, input_bytes=None: subprocess.CompletedProcess(["cryptsetup"], 0, DUMP_TPM, b"")
good = dict(NIXSEAL_DECL_SB="1", NIXSEAL_DECL_LUKS="cryptroot", NIXSEAL_DECL_LUKS_DEV=dv, NIXSEAL_DECL_TPM2="1", NIXSEAL_DECL_FIDO2="0")
rc, out = run_doctor(good)
check("cmd_doctor 정상 → 종료 0, OK 줄 출력", rc == 0 and "[OK]" in out and "[FAIL]" not in out, out)
rc, out = run_doctor(good, ["--brief"])
check("--brief: 정상이면 아무 것도 출력하지 않는다", rc == 0 and out == "", repr(out))
M._pcrlock_pcrs = lambda: [3, 13]
rc, out = run_doctor(good, ["--brief"])
check("PCR 7 빠짐 → 종료 1, --brief 에도 FAIL 이 보인다", rc == 1 and "[FAIL]" in out and "PCR 7" in out, out)
M._pcrlock_pcrs = lambda: [3, 7]
rc, out = run_doctor(dict(good, NIXSEAL_DECL_TPM2="0"), [])
check("WARN 만 있으면 종료 0", rc == 0 and "[WARN]" in out, out)
for k in [k for k in os.environ if k.startswith("NIXSEAL_DECL_")]:
    os.environ.pop(k)
rc, out = run_doctor({})
check("선언 값 없음 → 점검하지 않았다고 말하고 종료 0", rc == 0 and "점검하지 않았다" in out, out)

print(f"{n['ok']} 통과, {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
