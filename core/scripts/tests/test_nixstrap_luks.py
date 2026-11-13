#!/usr/bin/env python3
"""nixstrap LUKS 복구 암호 생성(nixstrap.lib-luks.py)·셸 흐름(nixstrap.lib-luks.sh) 시험.
실행: python3 -I core/scripts/tests/test_nixstrap_luks.py   (cryptsetup·qrencode·lsblk·wipefs 는 가짜 실행 파일로 대체)"""
import importlib.util, os, shutil, stat, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(HERE)
n = {"ok": 0, "bad": 0}


def check(name, cond, extra=""):
    n["ok" if cond else "bad"] += 1
    if not cond:
        print("  FAIL", name, extra)


spec = importlib.util.spec_from_file_location("lib_luks", os.path.join(SCRIPTS, "nixstrap.lib-luks.py"))
L = importlib.util.module_from_spec(spec); spec.loader.exec_module(L)

# ── 단어 목록 ──
words = L.load_words()
check("목록 7776개", len(words) == 7776)
check("목록 중복 없음", len(set(words)) == 7776)
check("빈 단어 없음", all(words))
check("하이픈 단어 번호 구분 가능", "drop-down" in words)
tmp = tempfile.mkdtemp()
bad = os.path.join(tmp, "bad.txt")
raw = open(L.WORDLIST, "rb").read()
open(bad, "wb").write(raw + b"77777\textra\n")
try:
    L.load_words(bad); check("변조된 목록 거부", False)
except ValueError:
    check("변조된 목록 거부", True)
r = subprocess.run([sys.executable, "-I", os.path.join(SCRIPTS, "nixstrap.lib-luks.py"), "check-wordlist"],
                   env={"NIXSTRAP_WORDLIST": bad}, capture_output=True, text=True)
check("check-wordlist 변조 시 종료 1", r.returncode == 1)

# ── 생성 ──
pw = L.generate(8, words)
check("8단어", len(pw.split(" ")) == 8)
check("목록의 단어만", all(w in set(words) for w in pw.split(" ")))
check("소문자·공백 1칸", pw == L.normalize(pw))
check("엔트로피 103.4", abs(L.entropy_bits(8) - 103.4) < 0.05)
try:
    L.generate(5, words); check("6단어 미만 거부", False)
except ValueError:
    check("6단어 미만 거부", True)
check("6단어 허용", len(L.generate(6, words).split()) == 6)
calls = []
seq = iter([0, 1, 7775, 5, 6, 7, 8, 9])
L.generate(8, words, randbelow=lambda m: (calls.append(m), next(seq))[1])
check("randbelow(7776) 로만 뽑음(모듈로 편향 없음)", calls == [7776] * 8)
out = L.generate(3 + 3, words, randbelow=(lambda it: (lambda m: next(it)))(iter([0, 1, 2, 3, 4, 7775])))
check("인덱스→단어 결정적", out == " ".join(words[i] for i in [0, 1, 2, 3, 4, 7775]))
check("매번 다름", len({L.generate(8, words) for _ in range(20)}) == 20)
check("정규화", L.normalize("  Foo   BAR\t") == "foo bar")

# ── 셸 흐름 (가짜 cryptsetup 등) ──
shim = os.path.join(tmp, "shim"); os.makedirs(shim)
logd = os.path.join(tmp, "log"); os.makedirs(logd)


def mk(name, body):
    p = os.path.join(shim, name)
    open(p, "w").write("#!/usr/bin/env bash\n" + body)
    os.chmod(p, 0o755)


mk("cryptsetup", f'''L={logd}
printf '%s\\n' "$*" >> $L/argv
case "$*" in
  *luksFormat*) cat > $L/key ;;
  *--test-passphrase*) cat > $L/test; cmp -s $L/key $L/test ;;
  *) cat > $L/open ;;
esac''')
mk("qrencode", 'cat >/dev/null; echo "QRCODE"')
mk("lsblk", 'echo "nvme0n1 953.9G fake"')
mk("wipefs", 'echo "gpt"')

DRIVER = f'''
set -u
SCRIPT_DIR="{SCRIPTS}"
source "$SCRIPT_DIR/nixstrap.lib-ui.sh"
source "$SCRIPT_DIR/nixstrap.lib-luks.sh"
_LUKS=true
luks_generate_and_confirm /dev/nvme0n1; echo "RC1=$?"
if [ "${{1:-}}" = full ]; then
  luks_format_open /dev/fake1; echo "RC2=$?"
  luks_verify_typed /dev/fake1; echo "RC3=$?"
  luks_close; echo "RC4=$?"
fi
'''


def run(mode, answers_fn):
    """answers_fn(words:str)->str: 첫 읽기 직전(ssh 경고 줄)까지의 출력으로 암호를 알아낸 뒤 stdin 에 답을 넣는다."""
    for f in os.listdir(logd):
        os.remove(os.path.join(logd, f))
    env = {"PATH": shim + ":" + os.environ.get("PATH", ""), "TERM": "dumb", "LC_ALL": "C.UTF-8"}
    p = subprocess.Popen(["bash", "-c", DRIVER, "x", mode], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, env=env, text=True)
    head = []
    while True:
        line = p.stdout.readline()
        head.append(line)
        if "스크롤백" in line or not line:
            break
    shown = "".join(head)
    ws = [l.split(". ", 1)[1].strip() for l in shown.splitlines() if l.strip()[:2].rstrip(".").isdigit() and ". " in l]
    secret = " ".join(ws)
    stdout, _ = p.communicate(answers_fn(secret))
    return shown, shown + stdout, secret


def read_log(name):
    p = os.path.join(logd, name)
    return open(p, "rb").read() if os.path.exists(p) else b""


# 성공 경로
shown, full, secret = run("full", lambda s: "\n" + s.upper() + "\n/dev/nvme0n1\n" + s + "\n")
check("화면에 8단어 표시", len(secret.split()) == 8, secret)
check("QR 표시", "QRCODE" in shown)
check("대문자로 입력하면 정규화 경고(부팅 때는 정규화 안 됨)", "공백 1칸" in full, full[-500:])
check("RC1=0 RC2=0 RC3=0 RC4=0", all(f"RC{i}=0" in full for i in (1, 2, 3, 4)), full[-300:])
key = read_log("key")
check("luksFormat 키 = 암호(개행 없음)", key == secret.encode(), repr(key))
check("argv 에 암호 단어 없음", all(w not in read_log("argv").decode().split() for w in secret.split()))
after_clear = full.split("\x1b[3J", 1)[1] if "\x1b[3J" in full else full
check("화면 지움 시퀀스(스크롤백 포함)", "\x1b[2J\x1b[3J" in full)
check("지운 뒤 암호 단어 목록이 다시 나오지 않음", ". " + secret.split()[0] not in after_clear)
check("열림 검증 키도 개행 없음", read_log("test") == secret.encode())

# 재입력 3회 실패 → 중단, cryptsetup 미호출
shown, full, secret = run("gen", lambda s: "\nx\nx\nx\n")
check("3회 실패 → RC1=1", "RC1=1" in full, full[-300:])
check("실패 때 cryptsetup 불호출", read_log("argv") == b"")
check("실패 메시지에 '변경되지 않았습니다'", "변경되지 않았습니다" in full)

# 디스크 경로 불일치 → 중단
shown, full, secret = run("gen", lambda s: "\n" + s + "\n/dev/sda\n")
check("디스크 경로 불일치 → RC1=1", "RC1=1" in full, full[-300:])
check("경로 불일치 때 cryptsetup 불호출", read_log("argv") == b"")

# 2번째 시도 성공(첫 시도 오입력)
shown, full, secret = run("gen", lambda s: "\nwrong\n\n" + s + "\n/dev/nvme0n1\n")
check("재시도 후 성공", "RC1=0" in full, full[-300:])

# qrencode 없으면 단어만
os.remove(os.path.join(shim, "qrencode"))
shown, full, secret = run("gen", lambda s: "\n" + s + "\n/dev/nvme0n1\n")
check("qrencode 없어도 진행·단어 표시", "RC1=0" in full and len(secret.split()) == 8)

shutil.rmtree(tmp, ignore_errors=True)
print(f"\nnixstrap-luks {n['ok']} 통과 / {n['bad']} 실패")
sys.exit(1 if n["bad"] else 0)
