#!/usr/bin/env python3
"""luksctl — LUKS2 헤더 백업·검증·복원·키슬롯 조회 (ISO 의 저장소 클론에서도 쓰는 단독 스크립트)

사용:
  luksctl backup-header <장치|파일> <대상디렉터리> [--name 접두사]   헤더를 대상에 백업(파일명에 장치 UUID·시각, 권한 0400)
  luksctl verify <장치|백업파일> [--passphrase]                      LUKS 헤더인지 확인(+ --passphrase: 암호를 숨겨 입력받아 열림 검사)
  luksctl slots <장치|백업파일>                                      키슬롯·토큰 요약
  luksctl restore-header <장치> <백업파일>                           백업을 장치에 되돌림(되돌릴 수 없음: 장치 경로를 직접 입력해야 진행)

주의(헤더 백업은 「그 시점의 암호/키슬롯으로 열리는 헤더」다): 이후 슬롯을 추가·삭제·변경하면 옛 백업은 옛 암호로만 열린다.
설치 직후 백업은 복구 암호만 아는 헤더이며, TPM2·FIDO2 등록(S5·S6) 뒤에는 다시 백업한다.
exFAT/FAT 매체는 0400 권한이 의미가 없으니 평문 접근이 가능한 매체임을 알고 쓴다(헤더 자체는 암호 없이 데이터를 열 수 없다).
환경변수 CRYPTSETUP 으로 실행 파일을 바꿀 수 있다(시험용).
"""
import datetime
import getpass
import os
import re
import subprocess
import sys

CRYPTSETUP = os.environ.get("CRYPTSETUP", "cryptsetup")

RESEAL_NOTICE = ("※ 이 백업은 지금의 키슬롯 구성으로만 열립니다. 슬롯을 추가·삭제·변경(TPM2/FIDO2/암호 교체)하면 "
                 "옛 백업은 옛 암호로만 열리므로, 그 뒤에는 다시 백업하세요.")


def _run(args, input_bytes=None, check=True):
    return subprocess.run([CRYPTSETUP, *args], input=input_bytes, capture_output=True, check=False)


def _die(msg, code=1):
    print(f"오류: {msg}", file=sys.stderr)
    sys.exit(code)


def luks_uuid(target):
    r = _run(["luksUUID", target])
    if r.returncode != 0:
        _die(f"{target}: LUKS 헤더를 읽지 못했습니다 ({r.stderr.decode(errors='replace').strip()})")
    return r.stdout.decode().strip()


def cmd_backup_header(args):
    name = "luks-header"
    if "--name" in args:
        i = args.index("--name")
        name = args[i + 1]
        del args[i:i + 2]
        if not name or name.startswith("-") or os.sep in name or name in (".", ".."):
            _die(f"--name 은 파일 이름 접두사여야 합니다(경로 구분자·'-' 시작 불가): {name}", 2)
    if len(args) != 2:
        _die("사용: luksctl backup-header <장치|파일> <대상디렉터리> [--name 접두사]", 2)
    dev, dest = args
    if not os.path.isdir(dest):
        _die(f"대상 디렉터리가 없습니다: {dest}")
    if not os.access(dest, os.W_OK):
        _die(f"대상에 쓸 수 없습니다: {dest}")
    uuid = luks_uuid(dev)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(dest, f"{name}-{uuid}-{stamp}.img")
    if os.path.exists(out):
        _die(f"이미 있습니다: {out}")
    r = _run(["luksHeaderBackup", dev, "--header-backup-file", out])
    if r.returncode != 0:
        _die(f"헤더 백업 실패: {r.stderr.decode(errors='replace').strip()}")
    try:
        os.chmod(out, 0o400)
    except OSError:
        pass
    # 백업 파일이 실제로 LUKS 헤더인지, UUID 가 같은지 확인
    if _run(["isLuks", out]).returncode != 0 or luks_uuid(out) != uuid:
        _die(f"백업 검증 실패: {out}")
    print(out)
    print(RESEAL_NOTICE, file=sys.stderr)


def cmd_verify(args):
    ask = "--passphrase" in args
    args = [a for a in args if a != "--passphrase"]
    if len(args) != 1:
        _die("사용: luksctl verify <장치|백업파일> [--passphrase]", 2)
    target = args[0]
    if _run(["isLuks", target]).returncode != 0:
        _die(f"{target}: LUKS 헤더가 아닙니다")
    print(f"ok LUKS 헤더 UUID={luks_uuid(target)}")
    if ask:
        pw = getpass.getpass("복구 암호(입력은 보이지 않음): ")
        r = _run(["open", "--test-passphrase", "--key-file=-", target], input_bytes=pw.encode())
        pw = ""
        if r.returncode != 0:
            _die("이 암호로 열리지 않습니다", 3)
        print("ok 암호로 열림 확인")


def parse_slots(dump):
    """luksDump 출력에서 키슬롯·토큰 요약을 뽑는다 → {'slots': [(번호, 종류, pbkdf)], 'tokens': [(번호, 종류)]}"""
    slots, tokens, section, cur = [], [], None, None
    for line in dump.splitlines():
        if re.match(r"^(Keyslots|Tokens|Digests|Data segments):", line):
            section, cur = line.split(":")[0], None
            continue
        m = re.match(r"^\s{2}(\d+): (\S+)", line)
        if m and section == "Keyslots":
            cur = [int(m.group(1)), m.group(2), "?"]; slots.append(cur)
        elif m and section == "Tokens":
            tokens.append((int(m.group(1)), m.group(2)))
        elif section == "Keyslots" and cur and "PBKDF:" in line:
            cur[2] = line.split("PBKDF:")[1].strip()
    return {"slots": [tuple(s) for s in slots], "tokens": tokens}


def cmd_slots(args):
    if len(args) != 1:
        _die("사용: luksctl slots <장치|백업파일>", 2)
    r = _run(["luksDump", args[0]])
    if r.returncode != 0:
        _die(f"luksDump 실패: {r.stderr.decode(errors='replace').strip()}")
    info = parse_slots(r.stdout.decode())
    print(f"키슬롯 {len(info['slots'])}개:")
    for n, kind, kdf in info["slots"]:
        print(f"  슬롯 {n}: {kind} (PBKDF {kdf})")
    print(f"토큰 {len(info['tokens'])}개:" + ("" if info["tokens"] else " (없음)"))
    for n, kind in info["tokens"]:
        print(f"  토큰 {n}: {kind}")


def cmd_restore_header(args):
    if len(args) != 2:
        _die("사용: luksctl restore-header <장치> <백업파일>", 2)
    dev, bak = args
    if _run(["isLuks", bak]).returncode != 0:
        _die(f"{bak}: LUKS 헤더가 아닙니다")
    # 열려 있는(매핑된) 장치에는 복원하지 않는다
    try:
        kids = subprocess.run(["lsblk", "-rno", "TYPE", dev], capture_output=True, text=True).stdout.split()
    except FileNotFoundError:
        kids = []
    if "crypt" in kids:
        _die(f"{dev} 가 열려 있습니다(매퍼 존재). 먼저 cryptsetup close 로 닫으세요.")
    cur = _run(["luksUUID", dev])
    new_uuid = luks_uuid(bak)
    differ = False
    if cur.returncode == 0:
        cur_uuid = cur.stdout.decode().strip()
        print(f"현재 장치 UUID: {cur_uuid}\n백업 파일 UUID: {new_uuid}")
        differ = cur_uuid != new_uuid
    else:
        print(f"현재 장치의 헤더를 읽지 못했습니다(손상됐다면 정상). 백업 파일 UUID: {new_uuid}")
    print(f"{dev} 의 현재 헤더를 {bak} 로 덮어씁니다. 이 장치의 현재 키슬롯은 사라집니다(되돌릴 수 없음).")
    if differ:
        print("경고: UUID 가 다릅니다 — 다른 디스크의 백업일 수 있습니다. 그 디스크의 헤더로 덮으면 이 장치의 데이터는 열리지 않게 됩니다.")
        if input("그래도 덮으려면 'overwrite' 를 입력하세요: ") != "overwrite":
            _die("중단합니다(변경 없음).")
    typed = input(f"계속하려면 장치 경로 '{dev}' 를 그대로 입력하세요: ")
    if typed != dev:
        _die("입력이 일치하지 않아 중단합니다(변경 없음).")
    r = _run(["luksHeaderRestore", dev, "--header-backup-file", bak, "--batch-mode"])
    if r.returncode != 0:
        _die(f"복원 실패: {r.stderr.decode(errors='replace').strip()}")
    print("ok 헤더 복원 완료")


COMMANDS = {"backup-header": cmd_backup_header, "verify": cmd_verify, "slots": cmd_slots, "restore-header": cmd_restore_header}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    COMMANDS[sys.argv[1]](sys.argv[2:])
