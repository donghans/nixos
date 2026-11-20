#!/usr/bin/env python3
"""nixseal — LUKS·Secure Boot 점검·복구 보조 (plan/nixseal). 단독 스크립트(표준 라이브러리만; `python3 -I` 로 실행 가능).

사용:
  nixseal status                                   Secure Boot + LUKS 슬롯 한 화면 요약
  nixseal doctor [--brief]                         nix 가 선언한 상태(luks·tpm2·fido2·secure-boot)와 실제(루트 암호화·LUKS 슬롯·pcrlock 정책·펌웨어 SB)를 비교해 어긋남을 알림(읽기 전용).
                                                   FAIL = 다음 부팅이 깨지거나 보호가 조용히 빠짐. nixup 이 배포 직후 자동으로 부른다(선언 값은 래퍼가 환경변수로 줌)
  nixseal sb status|verify                         SB·SetupMode, PK/KEK/db/dbx, 서명 키, ESP 서명, 백업, dbx 갱신 / sbctl verify
  nixseal sb backup-esp [경로]                     ESP(/boot) 전체를 tar 로 백업(기본 ~/esp-backup-YYYYMMDD.tar)
  nixseal sb enroll [--no-firmware-builtin]        Setup Mode 에서 키만 등록(sbctl enroll-keys --microsoft --firmware-builtin)
  nixseal sb dbx                                   dbx 가 비어 있으면 내장 DBXUpdate 로 채움(키 등록이 끝난 User Mode 에서만; 이미 있으면 아무 것도 안 함).
                                                   자동으로 하지 않는다 — dbx 가 바뀌면 PCR 7 이 달라져 TPM 등록이 깨지므로, 알림(sb-notify)을 보고 직접 한다
                                                   (집이고 낯선 사람이 없는지·바로 재부팅할 수 있는지 먼저 확인을 묻는다)
  nixseal sb dbx-update                            fwupd 의 dbx 등 갱신을 확인하고, 같은 확인을 거친 뒤 적용(fwupdmgr update)
  nixseal recover --evidence-dir <USB 경로> [--no-evidence] [--evidence-image] [--from-backup <esp-backup-*.tar>] [--root <장치>] [--pki <대상 안 경로>]
                                                   **ISO(신뢰 USB) 전용.** 의심스러운 ESP 를 증거로 보관 → 같은 라벨·볼륨 ID 로 포맷 → 루트의 서명 키로 재생성(--from-backup 이면 지정한 백업 복원).
                                                   복구 암호·FIDO2 를 이상한 화면에 입력했을 수 있으면 멈춘다(전부 엎기: nixseal luks reseal). TPM 은 건드리지 않고 첫 부팅 뒤 할 일을 안내한다
  nixseal tpm status [장치]                        TPM2 슬롯·정책 파일(보호 PCR)·ESP 의 정책 credential 요약(PCR 7 이 빠졌으면 경고)
  nixseal tpm enroll [--replace] [장치]            복구 암호로 연 상태에서 TPM2+PIN 슬롯 등록(PIN 은 이 부팅에만 쓰는 별도 구절). --replace: 기존 TPM2 슬롯 교체
  nixseal tpm refresh-policy [--force]             Secure Boot 를 직접 바꾼 직후, 재부팅 전에 TPM 정책을 새 상태로 갱신(「내가 한 변경」 확인). sb dbx·dbx-update 는 TPM 슬롯이 있으면 이것을 이어서 부른다
  nixseal pw seal [--user 계정] [--stdin]         (TPM+PIN 부팅 직후 로그인·키링 자동 해제용) 계정 비밀번호 P 를 TPM 에 봉인한다 — 인증값은 부팅 PIN 의 SHA-256.
                                                   부팅 PIN 은 로그인 비밀번호로 쓰이지 않고 P 를 푸는 열쇠일 뿐이다(mods.sys.services.tpm-login, SECURE-BOOT.md §2-15)
  nixseal pw status|test|remove [--user 계정]     봉인 상태(블롭·실패 표지) / PIN 으로 풀어 계정 비밀번호와 맞는지 확인(오입력은 TPM 카운터를 올린다) / 봉인 삭제
  nixseal luks slots <장치|백업파일>               키슬롯·토큰 요약
  nixseal luks backup <장치|파일> <대상디렉터리> [--name 접두사]   헤더 백업(파일명에 장치 UUID·시각, 권한 0400)
  nixseal luks verify <장치|백업파일> [--passphrase]              LUKS 헤더인지 확인(+ 암호를 숨겨 입력받아 열림 검사)
  nixseal luks restore <장치> <백업파일>           백업을 장치에 되돌림(되돌릴 수 없음: 장치 경로를 직접 입력해야 진행)
  nixseal luks reseal --backup-dir <디렉터리> <장치>   마스터키 교체 + 새 복구 암호(8단어)로 슬롯 재구성. 신뢰 USB(ISO)에서만, 장치가 닫혀 있어야 함.
                                                   백업 디렉터리는 마운트한 USB 등(RAM 디스크는 거부), 충전기 연결 필수, 도중에 끄지 말 것
  nixseal luks reseal --resume <장치>              중단된 reseal 을 이어서 끝냄(새 복구 암호 필요)   (자세한 안내: nixseal luks reseal --help)

환경변수(시험·nix 래퍼용): CRYPTSETUP, SBCTL, NIXSEAL_PCRLOCK, NIXSEAL_PCRLOCK_JSON, NIXSEAL_ESP_CRED, NIXSEAL_CRYPTENROLL, NIXSEAL_EFIVARS(기본 /sys/firmware/efi/efivars), NIXSEAL_PKI(기본 /var/lib/sbctl),
  NIXSEAL_DBX(내장 DBXUpdate.bin 경로), NIXSEAL_FWUPD_DIR(기본 /var/lib/fwupd-check), NIXSEAL_SELF(sudo 로 다시 실행할 래퍼 경로), NIXSEAL_NO_SUDO(시험용),
  NIXSEAL_PWSEAL_DIR(기본 /var/lib/nixseal/pwseal), NIXSEAL_TPM2_*·NIXSEAL_UNIX_CHKPWD(시험용), NIXSEAL_DECL_TPMLOGIN(doctor: 봉인 로그인 계정),
  NIXSEAL_DECL_SB|LUKS|LUKS_DEV|TPM2|FIDO2(doctor 가 비교할 nix 선언 — 없으면 그 칸을 건너뜀. LUKS 는 「빈 값 = luks 없음 선언」과 「설정 안 함 = 모름」이 다르다).

주의(헤더 백업은 「그 시점의 암호/키슬롯으로 열리는 헤더」다): 이후 슬롯을 추가·삭제·변경하면 옛 백업은 옛 암호로만 열린다.
보관할 백업은 복구 암호만 등록된 초기 상태 하나면 된다(마스터키·복구 암호를 바꿀 때만 새로 찍는다). FIDO2·TPM 은 복구 암호로 연 뒤 다시 등록한다.
exFAT/FAT 매체는 0400 권한이 의미가 없으니 평문 접근이 가능한 매체임을 알고 쓴다(헤더 자체는 암호 없이 데이터를 열 수 없다).
"""
import contextlib
import datetime
import getpass
import glob
import hashlib
import io
import os
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import time

CRYPTSETUP = os.environ.get("CRYPTSETUP", "cryptsetup")
SBCTL = os.environ.get("SBCTL", "sbctl")
EFIVARS = os.environ.get("NIXSEAL_EFIVARS", "/sys/firmware/efi/efivars")
PKI = os.environ.get("NIXSEAL_PKI", "/var/lib/sbctl")
DBX_BUNDLED = os.environ.get("NIXSEAL_DBX", "")
FWUPD_DIR = os.environ.get("NIXSEAL_FWUPD_DIR", "/var/lib/fwupd-check")
FWUPDMGR = os.environ.get("FWUPDMGR", "fwupdmgr")
HOME_ACK = "집이고 바로 재부팅"
G_GLOBAL = "8be4df61-93ca-11d2-aa0d-00e098032b8c"  # EFI_GLOBAL_VARIABLE (PK, KEK, SecureBoot, SetupMode, *Default)
G_DB = "d719b2cb-3d3a-4596-a3bc-dad00e67656f"      # EFI_IMAGE_SECURITY_DATABASE (db, dbx)
CRYPTROOT = "/dev/disk/by-partlabel/cryptroot"

RESEAL_NOTICE = ("※ 이 백업은 지금의 키슬롯 구성으로만 열립니다. 슬롯을 추가·삭제·변경(TPM2/FIDO2/암호 교체)하면 "
                 "옛 백업은 옛 암호로만 열리므로, 마스터키나 복구 암호를 바꾼 뒤에는 다시 백업하세요.")


def _die(msg, code=1):
    print(f"오류: {msg}", file=sys.stderr)
    sys.exit(code)


def _run(cmd, input_bytes=None):
    return subprocess.run(cmd, input=input_bytes, capture_output=True, check=False)


def _need_root(args):
    """root 가 아니면 래퍼(NIXSEAL_SELF, 없으면 이 스크립트)를 sudo 로 다시 실행한다."""
    if os.geteuid() == 0 or os.environ.get("NIXSEAL_NO_SUDO"):  # NIXSEAL_NO_SUDO: 시험용(권한 상승을 건너뛸 뿐 높이지는 않는다)
        return
    me = os.environ.get("NIXSEAL_SELF")
    cmd = ["sudo", me] if me else ["sudo", sys.executable, os.path.abspath(__file__)]
    os.execvp("sudo", cmd + args)


# ───────────────────────── Secure Boot (sb) ─────────────────────────

def var_path(name, guid):
    return os.path.join(EFIVARS, f"{name}-{guid}")


def var_size(name, guid):
    """efivars 변수의 본문 바이트 수(속성 4바이트 제외). 없으면 None."""
    p = var_path(name, guid)
    return os.path.getsize(p) - 4 if os.path.exists(p) else None


def var_byte(name, guid):
    """efivars 변수의 첫 본문 바이트. 없거나 못 읽으면 None."""
    try:
        with open(var_path(name, guid), "rb") as f:
            b = f.read()  # efivarfs 는 seek 를 지원하지 않는다(통째로 읽고 속성 4바이트 뒤를 본다)
        return b[4] if len(b) > 4 else None
    except OSError:
        return None


def is_factory(name):
    """PK|KEK 가 공장 기본값(<name>Default)과 같은가."""
    a, b = var_path(name, G_GLOBAL), var_path(f"{name}Default", G_GLOBAL)
    if not (os.path.exists(a) and os.path.exists(b)):
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        return fa.read()[4:] == fb.read()[4:]


def _fmt(n):
    return "없음" if n is None else str(n)


def sb_status(full=True):
    print("== Secure Boot 상태 ==")
    sb, sm = var_byte("SecureBoot", G_GLOBAL), var_byte("SetupMode", G_GLOBAL)
    if sb is None and sm is None:
        print("EFI 변수를 읽지 못함(UEFI 로 부팅하지 않았거나 efivarfs 가 없음)")
        return
    print(f"SecureBoot: {'켜짐' if sb == 1 else '꺼짐'}   SetupMode: {'켜짐(키 등록 가능)' if sm == 1 else '꺼짐(User Mode)'}")
    print()
    print("== 펌웨어 키 데이터베이스(본문 바이트) ==")
    for v in ("PK", "KEK"):
        note = ""
        if os.path.exists(var_path(v, G_GLOBAL)):
            note = "공장 기본값과 같음(우리 키 아님)" if is_factory(v) else "공장 기본값과 다름(사용자 키 포함)"
        print(f"{v:<4} {_fmt(var_size(v, G_GLOBAL)):>8}  {note}")
    print(f"{'db':<4} {_fmt(var_size('db', G_DB)):>8}")
    dbx_note = "" if os.path.exists(var_path("dbx", G_DB)) else "← 없음: nixseal sb dbx 로 채운다(로그인 때 알림이 뜸)"
    print(f"{'dbx':<4} {_fmt(var_size('dbx', G_DB)):>8}  {dbx_note}")
    if not full:
        return
    print()
    print("== 서명 키(디스크) ==")
    for k in ("PK", "KEK", "db"):
        p = f"{PKI}/keys/{k}/{k}.key"
        print(f"{k}: 있음" if os.path.exists(p) else f"{k}: 없음 ({p})")
    print()
    print("== ESP 서명 검증(sbctl verify) ==")
    r = subprocess.run([SBCTL, "verify"], capture_output=True, text=True)
    out = (r.stdout or "") + (r.stderr or "")
    lines = out.splitlines()
    bad = [ln for ln in lines if "✗" in ln]
    print(f"서명됨: {sum(1 for ln in lines if '✓' in ln)}개, 서명 안 됨: {len(bad)}개")
    for ln in bad:
        print("  " + ln)
    print("  (EFI/nixos/kernel-*.efi 는 lanzaboote 가 서명 UKI 에 박은 해시로 검증하므로 서명 안 됨으로 나와도 정상)")
    print()
    print("== 백업 ==")
    found = glob.glob("/home/*/esp-backup-*.tar")
    if found:
        newest = max(found, key=os.path.getmtime)
        print(f"ESP 백업: {newest} ({int((time.time() - os.path.getmtime(newest)) // 86400)}일 전)")
    else:
        print("ESP 백업: 없음 — nixseal sb backup-esp")
    print()
    print("== dbx 갱신(fwupd) ==")
    res = os.path.join(FWUPD_DIR, "last-result")
    if os.path.isfile(res):
        print("마지막 확인: " + datetime.datetime.fromtimestamp(os.path.getmtime(res)).strftime("%F %T"))
        with open(res, errors="replace") as f:
            ups = [ln.rstrip("\n") for ln in f if "New version" in ln]
        if ups:
            for ln in ups:
                print("  갱신 있음: " + ln)
        else:
            print("  갱신 없음(마지막 확인 기준)")
    else:
        print("fwupd 확인 기록 없음(fwupd 모듈이 꺼져 있거나 아직 안 돌았음)")


def cmd_sb_status(args):
    _need_root(["sb", "status"] + args)
    sb_status(full=shutil.which(SBCTL) is not None)


def cmd_sb_verify(args):
    _need_root(["sb", "verify"] + args)
    subprocess.run([SBCTL, "verify"])
    print("(EFI/nixos/kernel-*.efi 의 '서명 안 됨'은 정상: 서명 UKI 의 해시로 검증)")


def cmd_sb_backup_esp(args):
    _need_root(["sb", "backup-esp"] + args)
    user = os.environ.get("SUDO_USER") or os.environ.get("USER") or "root"
    try:
        home = pwd.getpwnam(user).pw_dir
    except KeyError:
        home = os.path.expanduser("~")
    dest = args[0] if args else os.path.join(home, f"esp-backup-{datetime.date.today():%Y%m%d}.tar")
    r = subprocess.run(["tar", "-C", "/boot", "-cf", dest, "."])
    if r.returncode != 0:
        _die("tar 실패")
    if os.environ.get("SUDO_USER"):
        try:
            shutil.chown(dest, user=os.environ["SUDO_USER"])
        except (LookupError, OSError):
            pass
    os.chmod(dest, 0o600)
    n = len(subprocess.run(["tar", "-tf", dest], capture_output=True, text=True).stdout.splitlines())
    print(f"ESP 백업: {dest} ({os.path.getsize(dest) // 1024}KiB, {n}개 항목)")
    print("복구용 USB 에도 복사해 둘 것.")


def apply_dbx(binpath):
    """DBXUpdate .bin(인증 헤더+서명 목록)을 dbx 변수가 없을 때 처음 한 번 채운다(펌웨어가 KEK 서명을 검증)."""
    import struct
    with open(binpath, "rb") as f:
        data = f.read()
    attr = 0x01 | 0x02 | 0x04 | 0x20 | 0x40  # NV|BS|RT|TIME_BASED_AUTH|APPEND_WRITE
    fd = os.open(var_path("dbx", G_DB), os.O_WRONLY | os.O_CREAT, 0o644)
    try:
        n = os.write(fd, struct.pack("<I", attr) + data)
        print("쓴 바이트", n)
    finally:
        os.close(fd)
    print(f"dbx 크기: {_fmt(var_size('dbx', G_DB))}바이트. 이후 갱신은 fwupdmgr 로.")


def _confirm_chain_change(what, tpm=False):
    """Secure Boot 상태(PCR 7)를 바꾸는 작업 전 확인. 집처럼 안전한 곳·낯선 사람 없음·끝난 뒤 바로 재부팅할 수 있을 때만 진행한다."""
    print(what)
    if tpm:
        print("※ 이 변경은 Secure Boot 상태(PCR 7)를 바꿉니다. TPM+PIN 을 쓰는 중이라, 변경 직후 **같은 명령 안에서 TPM 정책을 이어서 갱신**합니다 — 끝날 때까지 기다리고, 끝나면 바로 재부팅하세요.")
        print("   정책 갱신은 재부팅 전에만 가능합니다(재부팅한 뒤에는 복구 암호 + 재등록뿐).")
    else:
        print("※ 이 변경은 Secure Boot 상태(PCR 7)를 바꿔 TPM+PIN 등록이 깨질 수 있습니다. 적용 뒤 **자리를 비우지 말고 바로 재부팅**해서 복구 암호를 한 번 입력하고 TPM 을 다시 등록해야 합니다.")
    print("   집처럼 안전한 곳에서, 곁에 낯선 사람이 없고, 끝나면 바로 재부팅할 수 있을 때만 하세요.")
    print("   [왜] 변경 순간부터 재부팅까지는 기기가 새 상태와 TPM 이 아는 옛 상태가 어긋난 구간이고, 그 사이에 남이 손대면 구별할 수 없습니다.")
    print("        또 이 구간을 중간에 끊고 재부팅하면 TPM 이 열리지 않아 복구 암호를 입력해야 합니다.")
    if _ask(f"그렇다면 '{HOME_ACK}' 를 그대로 입력하세요: ") != HOME_ACK:
        print("취소 — 아무 것도 바꾸지 않았습니다.", file=sys.stderr)
        return False
    return True


def _dbx_fill():
    """dbx 가 없으면 내장 DBXUpdate 로 채운다(비대화형, 펌웨어가 KEK 서명을 검증). 0=채움·이미 있음, 1=못 채움."""
    if os.path.exists(var_path("dbx", G_DB)):
        print(f"dbx 가 이미 있다({_fmt(var_size('dbx', G_DB))}바이트). 갱신은 fwupdmgr(refresh → get-updates → update)로.")
        return 0
    if var_byte("SetupMode", G_GLOBAL) != 0:
        print("키가 아직 등록되지 않았다(Setup Mode 이거나 EFI 변수를 읽지 못함) — 먼저 nixseal sb enroll", file=sys.stderr)
        return 1
    if not DBX_BUNDLED or not os.path.isfile(DBX_BUNDLED):
        print(f"내장 DBXUpdate 를 찾지 못함({DBX_BUNDLED or '미설정'})", file=sys.stderr)
        return 1
    tpm = _has_tpm_slot()
    unknown = _tpm_unknown
    if unknown:
        print(UNKNOWN_TPM_NOTE, file=sys.stderr)
    if not _confirm_chain_change("dbx 가 비어 있어 내장 DBXUpdate 로 채우려 합니다(커밋 고정, 펌웨어가 KEK 서명을 검증).", tpm):
        return 1
    try:
        apply_dbx(DBX_BUNDLED)
    except OSError as e:
        print(f"dbx 쓰기 실패: {e}", file=sys.stderr)
        return 1
    return 0 if _after_chain_change(tpm) else 1


def cmd_sb_dbx(args):
    _need_root(["sb", "dbx"] + args)
    if args:
        _die(f"알 수 없는 인자: {args[0]} (사용법: nixseal sb dbx)", 2)
    sys.exit(_dbx_fill())


def cmd_sb_dbx_update(args):
    """fwupd 의 dbx(등) 갱신을 확인하고, 확인 절차를 거친 뒤 적용한다. 자동으로 하지 않는다 — TPM 등록이 깨질 수 있으므로."""
    _need_root(["sb", "dbx-update"] + args)
    if args:
        _die(f"알 수 없는 인자: {args[0]} (사용법: nixseal sb dbx-update)", 2)
    if not os.path.exists(var_path("dbx", G_DB)):
        _die("dbx 가 비어 있다 — fwupd 는 빈 dbx 의 갱신을 거부한다. 먼저 nixseal sb dbx")
    r = subprocess.run([FWUPDMGR, "get-updates"])
    if r.returncode == 2:
        print("적용할 갱신이 없다.")
        return
    if r.returncode != 0:
        _die(f"{FWUPDMGR} get-updates 실패(rc={r.returncode})")
    tpm = _has_tpm_slot()
    unknown = _tpm_unknown
    if unknown:
        print(UNKNOWN_TPM_NOTE, file=sys.stderr)
    if not _confirm_chain_change("위 fwupd 갱신을 적용하려 합니다(dbx 등 Secure Boot 데이터베이스).", tpm):
        sys.exit(1)
    if subprocess.run([FWUPDMGR, "update", "-y", "--no-reboot-check"]).returncode != 0:
        if tpm or unknown:  # fwupd 는 여러 항목을 처리하다 중간에 실패할 수 있다 — 그때 dbx 는 이미 바뀌었을 수 있다
            print("※ 실패했지만 일부 갱신(dbx 등)이 이미 적용됐을 수 있습니다. 재부팅하기 전에 `nixseal sb status` 로 확인하고, "
                  "바뀌었다면 `nixseal tpm refresh-policy` 를 해야 합니다(재부팅하면 복구 암호 + 재등록).", file=sys.stderr)
        _die("fwupdmgr update 실패")
    try:  # 알림(sb-notify)이 멈추도록 결과 파일을 다시 쓴다
        after = subprocess.run([FWUPDMGR, "get-updates"], capture_output=True, text=True)
        with open(os.path.join(FWUPD_DIR, "last-result"), "w") as f:
            f.write(after.stdout + after.stderr)
    except OSError:
        pass
    if tpm:
        if not _after_chain_change(tpm):
            sys.exit(1)
        print("적용했습니다. 이제 자리를 비우지 말고 바로 재부팅하세요 → PIN 만으로 열립니다.")
    else:
        print("적용했습니다. 이제 자리를 비우지 말고 바로 재부팅하세요 → 복구 암호 입력 → TPM+PIN 을 쓰는 중이면 다시 등록.")


def cmd_sb_enroll(args):
    _need_root(["sb", "enroll"] + args)
    builtin = True
    for a in args:
        if a == "--no-firmware-builtin":
            builtin = False  # 펌웨어에 기본 인증서(dbDefault)가 없는 환경(VM 의 OVMF 등)
        else:
            _die(f"알 수 없는 옵션: {a} (사용법: nixseal sb enroll [--no-firmware-builtin])", 2)
    if var_byte("SetupMode", G_GLOBAL) != 1:
        _die("Setup Mode 가 아니다. BIOS 에서: Factory Default Key Provisioning=Disabled → Reset To Setup Mode → 저장 후 부팅. (SECURE-BOOT.md 참고)")
    cmd = [SBCTL, "enroll-keys", "--microsoft"] + (["--firmware-builtin"] if builtin else [])
    if subprocess.run(cmd).returncode != 0:
        _die("키 등록 실패")
    print("키 등록 완료.")
    print("다음: BIOS 에서 Secure Boot Support 를 Enabled 로 바꾸고 저장 후 부팅. dbx 가 비어 있으면 로그인 때 알림이 뜬다 — 직접 채우려면 nixseal sb dbx(TPM 슬롯이 있으면 이어서 정책도 갱신한다).")
    print("그 뒤 nixseal sb status 로 확인.")


# ───────────────────────── TPM2+PIN (tpm, pcrlock) ─────────────────────────
# 근거: plan/boot-security 6-S6·6-S6a(VM 시험 core/scripts/tests/vm). 정책(NV 인덱스)은 「현재 PCR 상태가 옛 정책을 만족할 때만」 갱신된다 —
# 그래서 Secure Boot 변경(dbx 등)과 정책 갱신은 재부팅 전에 한 번에 끝내야 한다. 놓치면 복구 암호 + 재등록(remove-policy)뿐이다.

def _find_pcrlock():
    env = os.environ.get("NIXSEAL_PCRLOCK")
    if env:
        return env
    return shutil.which("systemd-pcrlock") or "/run/current-system/sw/lib/systemd/systemd-pcrlock"


PCRLOCK_JSON = os.environ.get("NIXSEAL_PCRLOCK_JSON", "/var/lib/systemd/pcrlock.json")
ESP_CRED_DIR = os.environ.get("NIXSEAL_ESP_CRED", "/boot/loader/credentials")
CRYPTENROLL = os.environ.get("NIXSEAL_CRYPTENROLL", "systemd-cryptenroll")
REFRESH_ACK = "내가 한 변경"
TRUST_ACK = "이 상태를 신뢰"
RETRY_HINT = "※ 아직 재부팅하지 마세요 — 재부팅 전이면 `nixseal tpm refresh-policy` 를 다시 해서 마칠 수 있습니다. 재부팅하면 갱신이 거부되고 복구 암호 + 재등록(remove-policy)뿐입니다."


BLKID = os.environ.get("NIXSEAL_BLKID", "blkid")
_tpm_unknown = False   # 마지막 _has_tpm_slot 이 「없다」가 아니라 「확인하지 못했다」였는가


def _luks_dev(args):
    """대상 LUKS 장치: 인자 > by-partlabel/cryptroot > 시스템에 LUKS 장치가 정확히 하나일 때 그것(luks mod 의 device 가 다른 경로여도 찾는다)."""
    if args:
        return args[0]
    if os.path.exists(CRYPTROOT):
        return CRYPTROOT
    try:
        r = subprocess.run([BLKID, "-t", "TYPE=crypto_LUKS", "-o", "device"], capture_output=True, text=True)
    except OSError:
        return ""
    devs = [d for d in r.stdout.split() if d]
    return devs[0] if len(devs) == 1 else ""


def _has_tpm_slot(dev=None):
    """장치에 systemd-tpm2 토큰이 있는가. 장치를 못 찾거나 읽지 못하면 False 를 돌려주되 _tpm_unknown 을 켠다
    (호출한 쪽이 「TPM 을 안 쓴다」가 아니라 「확인하지 못했다」고 경고해야 한다 — 조용히 정책 갱신을 건너뛰면 재부팅 뒤 재등록이 필요해진다)."""
    global _tpm_unknown
    _tpm_unknown = False
    dev = dev or _luks_dev([])
    if not dev:
        _tpm_unknown = True
        return False
    try:
        r = _cs(["luksDump", dev])
    except OSError:
        _tpm_unknown = True
        return False
    if r.returncode != 0:
        _tpm_unknown = True
        return False
    return any(k == "systemd-tpm2" for _, k in parse_slots(r.stdout.decode(errors="replace"))["tokens"])


UNKNOWN_TPM_NOTE = ("※ LUKS 장치를 찾지 못하거나 읽지 못해 TPM 슬롯이 있는지 확인하지 못했습니다. TPM+PIN 을 쓰는 중이면 이 변경 직후 "
                    "재부팅하기 전에 `nixseal tpm refresh-policy` 를 직접 하세요(재부팅하면 복구 암호 + 재등록).")


PCRLOCK_D = os.environ.get("NIXSEAL_PCRLOCK_D", "/var/lib/pcrlock.d")
VARIANT_BOOT_FILE = os.environ.get("NIXSEAL_VARIANT_BOOT", "/var/lib/nixseal/pcrlock-variants-boot")
BOOT_ID_FILE = os.environ.get("NIXSEAL_BOOT_ID_FILE", "/proc/sys/kernel/random/boot_id")


def _read_text(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _secureboot_policy_dir():
    d = sorted(glob.glob(os.path.join(PCRLOCK_D, "*-secureboot-policy.pcrlock.d")))
    return d[0] if d else None


def _read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _keep_previous_state_variant(prev):
    """Secure Boot 정책 구성요소를 다시 만든 직후 호출한다(prev = 다시 만들기 전의 generated.pcrlock 내용).
    **dbx 등을 바꾼 직후 재부팅 전에 정책을 갱신하면 그냥은 PCR 7 이 정책에서 빠진다** — 이번 부팅의 측정 로그에는 바꾸기 전 값이 있어 새로 만든 구성요소와 맞지 않기 때문이다
    (VM 실험 2026-11-20). 바꾸기 전 상태를 변종(old-<해시>.pcrlock)으로 남기면 로그가 그 변종과 맞아 PCR 7 이 남고, 재부팅 뒤(새 상태)에도 정책이 통과한다.
    변종은 그 부팅 동안만 유효하다 — 다음 부팅의 첫 갱신에서 지운다(안 지우면 옛 상태가 영구히 허용된다). 변종을 둔 부팅은 VARIANT_BOOT_FILE 에 기록한다."""
    d = _secureboot_policy_dir()
    if d is None:
        return
    new = _read_bytes(os.path.join(d, "generated.pcrlock"))
    boot = _read_text(BOOT_ID_FILE)
    if _read_text(VARIANT_BOOT_FILE) != boot:   # 다른 부팅에서 만든 변종 — 이번 부팅의 로그와 무관하다
        for v in glob.glob(os.path.join(d, "old-*.pcrlock")):
            with contextlib.suppress(OSError):
                os.remove(v)
    if prev is not None and new is not None and prev != new:
        try:
            with open(os.path.join(d, "old-" + hashlib.sha256(prev).hexdigest()[:12] + ".pcrlock"), "wb") as f:
                f.write(prev)
            os.makedirs(os.path.dirname(VARIANT_BOOT_FILE), exist_ok=True)
            with open(VARIANT_BOOT_FILE, "w") as f:
                f.write((boot or "") + "\n")
        except OSError as e:
            print(f"경고: 이전 상태 변종을 저장하지 못했다({e}) — PCR 7 이 정책에서 빠질 수 있습니다.", file=sys.stderr)


def _pcrlock_refresh(force=False):
    """현재 EFI 변수로 다음 부팅의 PCR 7 을 예측해 정책을 갱신한다. 성공하면 True. 결과에 PCR 7 이 없으면 False(보호가 조용히 빠진 것).
    force: 예측이 현재 정책과 같아도 다시 쓴다. make-policy 는 같으면 「skipping update」 하고 ESP 의 credential 도 안 쓰므로,
    ESP 를 비웠거나 credential 이 없어졌을 때는 이것이 있어야 복구된다(VM 시험 E1·E2)."""
    pl = _find_pcrlock()
    out = ""
    _d0 = _secureboot_policy_dir()
    prev_generated = _read_bytes(os.path.join(_d0, "generated.pcrlock")) if _d0 else None
    for sub in ("lock-secureboot-policy", "lock-secureboot-authority", "make-policy"):
        try:
            r = subprocess.run([pl, sub] + (["--force"] if force and sub == "make-policy" else []), capture_output=True, text=True)
        except OSError as e:
            print(f"systemd-pcrlock 을 실행하지 못함({pl}): {e}", file=sys.stderr)
            return False
        out = r.stdout + r.stderr
        if r.returncode != 0:
            print(f"systemd-pcrlock {sub} 실패(rc={r.returncode}):\n{out.strip()}", file=sys.stderr)
            return False
        if sub == "lock-secureboot-policy":
            _keep_previous_state_variant(prev_generated)
    try:
        os.sync()  # ESP(vfat) 의 credential 이 디스크에 내려가야 한다(VM 시험에서 빠뜨리면 정책이 사라졌다)
    except OSError:
        pass
    if not re.search(r"PCRs in protection mask:.*\b7 \(", out):
        print("정책에서 PCR 7(Secure Boot 정책)이 빠졌습니다 — 이 상태로는 Secure Boot 변경을 TPM 이 감지하지 못합니다.\n"
              "원인 ① initrd 에 systemd-pcrphase-initrd·systemd-pcrosseparator 유닛이 꺼져 있다(`mods.sys.services.luks.tpm2 = true` 인지 확인, plan/boot-security 6-S6a ②).\n"
              "원인 ② Secure Boot 변수를 바꾼 뒤 바꾸기 전 상태가 기록돼 있지 않아 이번 부팅의 로그와 맞는 상태가 없다(정책을 한 번도 만들지 않은 채 바꿨다) — "
              "이미 바꿨다면 재부팅(복구 암호로 열림)한 뒤 `nixseal tpm refresh-policy` 를 다시 하세요.", file=sys.stderr)
        print(out.strip(), file=sys.stderr)
        return False
    _record_fingerprint()   # 정책을 만든 시점의 Secure Boot 지문 — doctor 가 「갱신 없이 상태가 바뀜」을 알아본다
    return True


def _pcrlock_pcrs():
    """정책 파일이 보호하는 PCR 번호 목록(없거나 못 읽으면 None)."""
    import json
    try:
        with open(PCRLOCK_JSON) as f:
            return sorted(p["pcr"] for p in json.load(f)["pcrValues"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def cmd_tpm_status(args):
    _need_root(["tpm", "status"] + args)
    dev = _luks_dev(args)
    print("== TPM+PIN(pcrlock) ==")
    if dev:
        print(f"장치: {dev} — TPM2 슬롯: " + ("있음" if _has_tpm_slot(dev) else "없음"))
    else:
        print(f"장치를 찾지 못함({CRYPTROOT} 없음) — nixseal tpm status <장치>")
    pcrs = _pcrlock_pcrs()
    if pcrs is None:
        print(f"정책 파일: 없음/읽지 못함({PCRLOCK_JSON})")
    else:
        print(f"정책 파일: {PCRLOCK_JSON} — 보호 PCR {pcrs}")
        if 7 not in pcrs:
            print("  경고: PCR 7(Secure Boot 정책)이 없습니다 — Secure Boot 변경을 TPM 이 감지하지 못합니다.")
    creds = _esp_credentials()
    print(f"ESP 의 정책 credential: {len(creds)}개" + ("" if not creds else " — " + ", ".join(os.path.basename(c) for c in creds)))
    if not creds:
        print("  (initrd 가 TPM 으로 열려면 이 파일이 필요합니다 — nixseal tpm refresh-policy: TPM 슬롯이 있으면 자동으로 다시 씁니다)")


def _esp_credentials():
    return sorted(glob.glob(os.path.join(ESP_CRED_DIR, "pcrlock.*.cred")))


def cmd_tpm_refresh_policy(args):
    """Secure Boot 상태를 바꾼 직후, 재부팅 전에 TPM 정책을 새 상태에 맞춘다. 사용자가 한 변경일 때만.
    --force: 상태가 그대로여도 정책과 ESP 의 credential 을 다시 쓴다(ESP 를 비웠거나 credential 이 없어졌을 때 — TPM 슬롯이 있는데 ESP 에 credential 이 없으면 자동으로 켠다)."""
    _need_root(["tpm", "refresh-policy"] + args)
    force = "--force" in args
    rest = [a for a in args if a != "--force"]
    if rest:
        _die(f"알 수 없는 인자: {rest[0]} (사용법: nixseal tpm refresh-policy [--force])", 2)
    if not force and not _esp_credentials() and _has_tpm_slot():
        force = True
        print("ESP 에 정책 credential 이 없습니다(ESP 를 비웠거나 지워짐) — 상태가 그대로여도 다시 쓰도록 --force 로 진행합니다.")
    print("TPM 정책을 지금의 Secure Boot 상태(다음 부팅에 측정될 값)로 갱신합니다.")
    print("※ 내가 방금 직접 한 변경(dbx 갱신 등)일 때만 하세요. 모르는 변경을 받아들이면 TPM 이 침해를 감지하지 못합니다.")
    print("   그런 변경이 없었다면 하지 말고, 신뢰 USB 로 점검하세요(SECURE-BOOT.md §2-10).")
    print("   [왜] TPM 이 부팅 상태가 달라졌다고 거부하는 것이 침해를 알리는 신호입니다. 정책을 갱신하면 그 신호가 꺼져, 바뀐 상태를 '정상'으로 받아들이게 됩니다.")
    if _ask(f"그렇다면 '{REFRESH_ACK}' 를 그대로 입력하세요: ") != REFRESH_ACK:
        print("취소 — 아무 것도 바꾸지 않았습니다.", file=sys.stderr)
        sys.exit(1)
    if not _pcrlock_refresh(force):
        print(RETRY_HINT, file=sys.stderr)
        sys.exit(1)
    print("정책을 갱신했습니다. 재부팅하면 PIN 만으로 열립니다.")


def cmd_tpm_enroll(args):
    """복구 암호로 연 상태에서 TPM2+PIN 슬롯을 등록한다(PIN 은 이 부팅에만 쓰는 별도 구절)."""
    _need_root(["tpm", "enroll"] + args)
    replace = "--replace" in args
    rest = [a for a in args if a != "--replace"]
    if any(a.startswith("-") for a in rest) or len(rest) > 1:
        _die("사용: nixseal tpm enroll [--replace] [장치]", 2)
    dev = _luks_dev(rest)
    if not dev:
        _die(f"장치를 찾지 못함({CRYPTROOT} 없음) — nixseal tpm enroll <장치>", 2)
    if _has_tpm_slot(dev) and not replace:
        _die("이미 TPM2 슬롯이 있다 — 바꾸려면 --replace(기존 TPM2 슬롯을 지우고 다시 등록)")
    print("지금의 부팅 상태(Secure Boot 키·dbx 등)를 TPM 이 받아들일 기준으로 등록합니다.")
    print("※ 신뢰 USB 점검을 마쳤고, 이 부팅이 내가 아는 정상 상태일 때만 하세요. PIN 은 이 부팅에만 쓰는 별도 구절로 정하세요.")
    print("   [왜] 지금 상태를 '정상'이라고 TPM 에 새기는 일입니다. 이미 변조된 상태에서 하면 변조된 상태가 기준이 되어 이후 감지되지 않습니다.")
    print("   PIN 을 따로 정하는 이유: 복구 암호와 같으면 가짜 화면에 한 번 입력한 것으로 둘 다 노출됩니다.")
    if _ask(f"그렇다면 '{TRUST_ACK}' 를 그대로 입력하세요: ") != TRUST_ACK:
        print("취소 — 아무 것도 바꾸지 않았습니다.", file=sys.stderr)
        sys.exit(1)
    if not _pcrlock_refresh(force=not _esp_credentials()):  # ESP 에 credential 이 없으면 정책이 같아도 다시 써야 initrd 가 TPM 으로 연다
        _die("정책을 만들지 못해 등록하지 않았다(위 메시지 참고)")
    cmd = [CRYPTENROLL] + (["--wipe-slot=tpm2"] if replace else []) + ["--tpm2-device=auto", f"--tpm2-pcrlock={PCRLOCK_JSON}", "--tpm2-with-pin=yes", dev]
    print("복구 암호를 묻고, 이어서 새 PIN 을 두 번 묻습니다.")
    if subprocess.run(cmd).returncode != 0:
        _die("systemd-cryptenroll 실패 — 등록이 실패하면 기존 슬롯은 지워지지 않는다(systemd-cryptenroll 문서: 등록이 끝난 뒤에만 --wipe-slot 을 실행). nixseal tpm status 로 확인")
    if not _esp_credentials():
        print(f"경고: ESP({ESP_CRED_DIR})에 정책 credential 이 없습니다 — 이대로 재부팅하면 TPM 으로 열리지 않고 복구 암호를 묻습니다. nixseal tpm refresh-policy --force", file=sys.stderr)
    print("등록했습니다. 다음 재부팅에서 PIN 만으로 열리는지 확인하세요(복구 암호는 그대로 남아 있습니다).")


def _after_chain_change(tpm):
    """Secure Boot 변경(dbx 등)이 끝난 직후, TPM 슬롯이 있으면 같은 확인 안에서 정책을 이어서 갱신한다. 실패하면 False."""
    if not tpm:
        return True
    print("이어서 TPM 정책을 갱신합니다.")
    if _pcrlock_refresh():
        print("정책을 갱신했습니다. 재부팅하면 PIN 만으로 열립니다.")
        return True
    print("※ Secure Boot 변경은 이미 적용됐지만 TPM 정책 갱신에 실패했습니다.", file=sys.stderr)
    print(RETRY_HINT, file=sys.stderr)
    return False


# ───────────────────────── LUKS (luks) ─────────────────────────

def _cs(args, input_bytes=None):
    return _run([CRYPTSETUP, *args], input_bytes)


def luks_uuid(target):
    r = _cs(["luksUUID", target])
    if r.returncode != 0:
        _die(f"{target}: LUKS 헤더를 읽지 못했습니다 ({r.stderr.decode(errors='replace').strip()})")
    return r.stdout.decode().strip()


def do_backup(dev, dest, name="luks-header"):
    """헤더를 dest 에 백업하고 경로를 돌려준다(검증 포함). 실패하면 종료."""
    if not os.path.isdir(dest):
        _die(f"대상 디렉터리가 없습니다: {dest}")
    if not os.access(dest, os.W_OK):
        _die(f"대상에 쓸 수 없습니다: {dest}")
    uuid = luks_uuid(dev)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(dest, f"{name}-{uuid}-{stamp}.img")
    if os.path.exists(out):
        _die(f"이미 있습니다: {out}")
    r = _cs(["luksHeaderBackup", dev, "--header-backup-file", out])
    if r.returncode != 0:
        _die(f"헤더 백업 실패: {r.stderr.decode(errors='replace').strip()}")
    try:
        os.chmod(out, 0o400)
    except OSError:
        pass
    # 백업 파일이 실제로 LUKS 헤더인지, UUID 가 같은지 확인
    if _cs(["isLuks", out]).returncode != 0 or luks_uuid(out) != uuid:
        _die(f"백업 검증 실패: {out}")
    return out


def cmd_luks_backup(args):
    args = list(args)
    name = "luks-header"
    if "--name" in args:
        i = args.index("--name")
        if i + 1 >= len(args):
            _die("--name 에 값이 필요합니다", 2)
        name = args[i + 1]
        del args[i:i + 2]
        if not name or name.startswith("-") or os.sep in name or name in (".", ".."):
            _die(f"--name 은 파일 이름 접두사여야 합니다(경로 구분자·'-' 시작 불가): {name}", 2)
    if len(args) != 2:
        _die("사용: nixseal luks backup <장치|파일> <대상디렉터리> [--name 접두사]", 2)
    dev, dest = args
    print(do_backup(dev, dest, name))
    print(RESEAL_NOTICE, file=sys.stderr)


def cmd_luks_verify(args):
    ask = "--passphrase" in args
    args = [a for a in args if a != "--passphrase"]
    if len(args) != 1:
        _die("사용: nixseal luks verify <장치|백업파일> [--passphrase]", 2)
    target = args[0]
    if _cs(["isLuks", target]).returncode != 0:
        _die(f"{target}: LUKS 헤더가 아닙니다")
    print(f"ok LUKS 헤더 UUID={luks_uuid(target)}")
    if ask:
        pw = getpass.getpass("복구 암호(입력은 보이지 않음): ")
        r = _cs(["open", "--test-passphrase", "--key-file=-", target], input_bytes=pw.encode())
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
            cur = [int(m.group(1)), m.group(2), "?"]
            slots.append(cur)
        elif m and section == "Tokens":
            tokens.append((int(m.group(1)), m.group(2)))
        elif section == "Keyslots" and cur and "PBKDF:" in line:
            cur[2] = line.split("PBKDF:")[1].strip()
    return {"slots": [tuple(s) for s in slots], "tokens": tokens}


def print_slots(target):
    r = _cs(["luksDump", target])
    if r.returncode != 0:
        _die(f"luksDump 실패: {r.stderr.decode(errors='replace').strip()}")
    info = parse_slots(r.stdout.decode())
    print(f"키슬롯 {len(info['slots'])}개:")
    for n, kind, kdf in info["slots"]:
        print(f"  슬롯 {n}: {kind} (PBKDF {kdf})")
    print(f"토큰 {len(info['tokens'])}개:" + ("" if info["tokens"] else " (없음)"))
    for n, kind in info["tokens"]:
        print(f"  토큰 {n}: {kind}")


def cmd_luks_slots(args):
    if len(args) != 1:
        _die("사용: nixseal luks slots <장치|백업파일>", 2)
    print_slots(args[0])


def cmd_luks_restore(args):
    if len(args) != 2:
        _die("사용: nixseal luks restore <장치> <백업파일>", 2)
    dev, bak = args
    if _cs(["isLuks", bak]).returncode != 0:
        _die(f"{bak}: LUKS 헤더가 아닙니다")
    # 열려 있는(매핑된) 장치에는 복원하지 않는다
    try:
        kids = subprocess.run(["lsblk", "-rno", "TYPE", dev], capture_output=True, text=True).stdout.split()
    except FileNotFoundError:
        kids = []
    if "crypt" in kids:
        _die(f"{dev} 가 열려 있습니다(매퍼 존재). 먼저 cryptsetup close 로 닫으세요.")
    cur = _cs(["luksUUID", dev])
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
        print("[왜 경고하나] LUKS 헤더에는 이 디스크를 여는 키슬롯이 들어 있어, 다른 디스크의 헤더로 덮으면 지금 데이터를 풀 키가 없어집니다.")
        print("경고: UUID 가 다릅니다 — 다른 디스크의 백업일 수 있습니다. 그 디스크의 헤더로 덮으면 이 장치의 데이터는 열리지 않게 됩니다.")
        if input("그래도 덮으려면 'overwrite' 를 입력하세요: ") != "overwrite":
            _die("중단합니다(변경 없음).")
    typed = input(f"계속하려면 장치 경로 '{dev}' 를 그대로 입력하세요: ")
    if typed != dev:
        _die("입력이 일치하지 않아 중단합니다(변경 없음).")
    r = _cs(["luksHeaderRestore", dev, "--header-backup-file", bak, "--batch-mode"])
    if r.returncode != 0:
        _die(f"복원 실패: {r.stderr.decode(errors='replace').strip()}")
    print("ok 헤더 복원 완료")


# ───────────────────────── reseal (마스터키 교체) ─────────────────────────
# plan/nixseal §4. 순서: 사전 점검 → 새 복구 암호 생성·종이 재입력 확인(여기까지 디스크 불변) → 경로 확인 → 되돌림용 헤더 백업
#   → 새 암호를 새 슬롯으로 추가·열림 확인(옛 슬롯 그대로) → cryptsetup reencrypt --key-slot <새 슬롯>(나머지 슬롯 제거, 토큰 정리) → 끝난 뒤 초기 상태 백업.
# 리허설(파일 이미지, 2026-11-19): 슬롯이 여럿이면 --key-file 은 --key-slot 과 함께만 쓸 수 있다 / --key-slot N 이면 나머지 슬롯은 사라지고 데이터는 보존 /
#   reencrypt 가 끝난 뒤 옛 헤더 백업을 복원하면 데이터가 깨진다(해시 불일치) / kill -9 뒤 `reencrypt --resume-only` 로 이어서 끝낼 수 있다 /
#   systemd-fido2 토큰은 슬롯이 사라진 뒤에도 남는다(그래서 토큰을 지운다).

POWER_SUPPLY_DIR = os.environ.get("NIXSEAL_POWER_DIR", "/sys/class/power_supply")
HERE = os.path.dirname(os.path.abspath(__file__))
WORDLIB = os.environ.get("NIXSEAL_WORDLIB", os.path.join(HERE, "nixstrap.lib-luks.py"))
MAX_TRIES = 3
BACKUP_ACK = "백업했음"


def _ask(prompt):
    return input(prompt)


def _ask_secret(prompt):
    return getpass.getpass(prompt)


def _clear_screen():
    sys.stdout.write("\033[2J\033[3J\033[H")
    sys.stdout.flush()
    if os.environ.get("TMUX"):
        subprocess.run(["tmux", "clear-history"], capture_output=True)


def _wordlib():
    import importlib.util
    if not os.path.isfile(WORDLIB):
        _die(f"복구 암호 생성기를 찾지 못함: {WORDLIB} (reseal 은 nixstrap 라이브러리가 있는 ISO 에서 쓴다)")
    spec = importlib.util.spec_from_file_location("nixstrap_lib_luks", WORDLIB)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _new_passphrase():
    lib = _wordlib()
    lib.load_words()  # 단어 목록 무결성 검사(어긋나면 예외)
    return lib.generate(8)


def _normalize(s):
    return " ".join(s.lower().split())


def _pw_opens(dev, pw):
    return _cs(["open", "--test-passphrase", "--key-file=-", dev], input_bytes=pw.encode()).returncode == 0


def _slot_numbers(dev):
    r = _cs(["luksDump", dev])
    if r.returncode != 0:
        _die(f"luksDump 실패: {r.stderr.decode(errors='replace').strip()}")
    return {n for n, _k, _d in parse_slots(r.stdout.decode())["slots"]}, parse_slots(r.stdout.decode())["tokens"]


def _is_luks2(dev):
    r = _cs(["luksDump", dev])
    return r.returncode == 0 and re.search(r"^Version:\s+2\b", r.stdout.decode(), re.M) is not None


def _fstype(path):
    r = subprocess.run(["stat", "-f", "-c", "%T", path], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def _is_open(dev):
    try:
        kids = subprocess.run(["lsblk", "-rno", "TYPE", dev], capture_output=True, text=True).stdout.split()
    except FileNotFoundError:
        kids = []
    return "crypt" in kids


def _on_ac_power():
    """AC 가 연결됐으면 True, 배터리뿐이면 False, 전원 정보가 없으면(데스크톱 등) None."""
    mains, battery = [], False
    for d in sorted(glob.glob(os.path.join(POWER_SUPPLY_DIR, "*"))):
        try:
            t = open(os.path.join(d, "type")).read().strip()
        except OSError:
            continue
        if t == "Mains":
            try:
                mains.append(open(os.path.join(d, "online")).read().strip() == "1")
            except OSError:
                pass
        elif t == "Battery":
            battery = True
    if any(mains):
        return True
    return False if battery else None


def _battery_percent():
    """배터리 잔량(%) 중 가장 낮은 값. 배터리가 없거나 읽지 못하면 None."""
    vals = []
    for d in sorted(glob.glob(os.path.join(POWER_SUPPLY_DIR, "*"))):
        try:
            if open(os.path.join(d, "type")).read().strip() == "Battery":
                vals.append(int(open(os.path.join(d, "capacity")).read().strip()))
        except (OSError, ValueError):
            continue
    return min(vals) if vals else None


def _show_qr(text):
    if shutil.which("qrencode") is None:
        print("(qrencode 없음 — QR 생략, 단어만 표시)")
        return
    r = subprocess.run(["qrencode", "-t", "ANSIUTF8", "-m", "2"], input=text.encode(), capture_output=True)
    if r.returncode != 0:
        return
    qr = r.stdout.decode()
    lines = qr.splitlines()
    cols = shutil.get_terminal_size((80, 24))
    if max((len(re.sub(r"\x1b\[[0-9;]*m", "", ln)) for ln in lines), default=0) <= cols.columns and len(lines) + 14 <= cols.lines:
        print(qr)
    else:
        print("(터미널이 작아 QR 생략 — 단어만 표시)")


def _record_new_passphrase(dev):
    """새 복구 암호를 만들어 보여 주고, 종이를 보고 다시 입력하게 해 확인한다. 성공하면 그 암호를 돌려준다. 실패하면 종료(디스크 불변)."""
    pw = _new_passphrase()
    lib = _wordlib()
    print()
    print(f"새 디스크 암호화 복구 암호 (영어 8단어, 약 {lib.entropy_bits(8):.1f}비트) — 지금 종이/보안 저장소에 기록하세요.")
    print(f"생성 시각 {datetime.datetime.now():%Y-%m-%d %H:%M} 도 함께 적어 두세요(옛 암호와 구분). 이 화면은 확인이 끝나면 다시 볼 수 없습니다.")
    print()
    for i, w in enumerate(pw.split(), 1):
        print(f"        {i}. {w}")
    print()
    _show_qr(pw)
    print("ssh 로 접속 중이면 클라이언트 터미널 스크롤백에 암호가 남습니다. 본체 화면에서 하세요.")
    _ask("기록을 마쳤으면 Enter (화면이 지워집니다): ")
    _clear_screen()
    want = _normalize(pw)
    for t in range(1, MAX_TRIES + 1):
        typed = _ask_secret(f"기록한 종이를 보고 새 복구 암호를 다시 입력하세요 [{t}/{MAX_TRIES}]: ")
        if _normalize(typed) == want:
            return want
        print("일치하지 않습니다.")
        if t < MAX_TRIES:
            print("\n다시 확인하세요(암호를 다시 보여 줍니다):")
            for i, w in enumerate(pw.split(), 1):
                print(f"        {i}. {w}")
            _ask("확인했으면 Enter: ")
            _clear_screen()
    _die(f"새 복구 암호 확인에 {MAX_TRIES}회 실패 — 중단합니다. (디스크는 변경되지 않았습니다)")


def _ask_current_passphrase(dev):
    for t in range(1, MAX_TRIES + 1):
        pw = _ask_secret(f"현재 복구 암호(지금 이 장치를 여는 암호) [{t}/{MAX_TRIES}]: ")
        if _pw_opens(dev, _normalize(pw)):
            return _normalize(pw)
        if _pw_opens(dev, pw):
            return pw
        print("이 암호로 열리지 않습니다.")
    _die("현재 암호 확인에 실패 — 중단합니다. (디스크는 변경되지 않았습니다)")


def _add_slot(dev, old_pw, new_pw):
    """old_pw 로 열어 new_pw 를 새 슬롯으로 추가한다(암호는 파이프로만 전달, 파일·인자에 남기지 않음). 새 슬롯 번호를 돌려준다."""
    before, _t = _slot_numbers(dev)
    r1, w1 = os.pipe()
    r2, w2 = os.pipe()
    os.write(w1, old_pw.encode()); os.close(w1)
    os.write(w2, new_pw.encode()); os.close(w2)
    extra = ["--pbkdf", "pbkdf2", "--pbkdf-force-iterations", "1000"] if os.environ.get("NIXSEAL_PBKDF_FAST") else []  # 시험용(빠르게)
    try:
        r = subprocess.run([CRYPTSETUP, "luksAddKey", "--batch-mode", *extra, "--key-file", f"/dev/fd/{r1}", dev, f"/dev/fd/{r2}"],
                           pass_fds=(r1, r2), capture_output=True)
    finally:
        os.close(r1); os.close(r2)
    if r.returncode != 0:
        _die(f"새 슬롯 추가 실패: {r.stderr.decode(errors='replace').strip()} (디스크의 기존 슬롯은 그대로입니다)")
    after, _t = _slot_numbers(dev)
    new = sorted(after - before)
    if len(new) != 1:
        _die(f"새 슬롯 번호를 알 수 없습니다(전 {sorted(before)} → 후 {sorted(after)}) — reencrypt 하지 않고 중단합니다")
    return new[0]


def _run_reencrypt(dev, new_pw, slot, resume, force_offline):
    cmd = [CRYPTSETUP, "reencrypt", "--batch-mode", "--key-file=-"]
    if resume:
        cmd.append("--resume-only")
    else:
        cmd += ["--key-slot", str(slot)]
    if force_offline:
        cmd.append("--force-offline-reencrypt")  # 파일 이미지 시험용(실제 블록 장치에는 필요 없음)
    cmd.append(dev)
    return subprocess.run(cmd, input=new_pw.encode()).returncode


def _repair(dev, pw):
    """정전·강제 종료 뒤에는 reencrypt 를 이어가기 전에 복구(repair)가 필요하다 — `Device requires reencryption recovery. Run repair first.`
    (2026-11-19 VM 에서 QEMU 를 갑자기 종료해 확인. 프로세스만 kill -9 한 경우는 필요 없었다.) 필요 없으면 cryptsetup 이 알아서 넘어간다."""
    r = _cs(["repair", "--batch-mode", "--key-file=-", dev], input_bytes=pw.encode())
    msg = (r.stdout + r.stderr).decode(errors="replace").strip()
    print(f"repair rc={r.returncode}" + (f": {msg}" if msg else ""))
    return r.returncode


def _finish_reseal(dev, new_pw, backup_dir, rollback):
    """reencrypt 가 끝난 뒤: 새 암호로 열림 확인 → 옛 슬롯을 가리키는 토큰 제거 → 초기 상태(복구 암호만) 헤더 백업 → 되돌림용 백업 삭제."""
    if not _pw_opens(dev, new_pw):
        _die("reencrypt 뒤 새 복구 암호로 열리지 않습니다 — 되돌림용 헤더 백업을 복원하지 말고(데이터가 깨질 수 있음) 상황을 확인하세요")
    slots, tokens = _slot_numbers(dev)
    for tid, _kind in tokens:
        _cs(["token", "remove", "--token-id", str(tid), dev])
    print(f"ok 새 복구 암호로 열림 확인. 남은 키슬롯: {sorted(slots)}, 제거한 토큰(옛 FIDO2/TPM 등): {[t[0] for t in tokens] or '없음'}")
    out = do_backup(dev, backup_dir)
    print(f"초기 상태(복구 암호만 등록) 헤더 백업: {out}")
    if rollback and os.path.exists(rollback):
        try:
            os.remove(rollback)
            print(f"되돌림용 백업 삭제: {rollback}")
        except OSError as e:
            print(f"되돌림용 백업을 지우지 못함({e}) — 직접 지우세요(reencrypt 뒤에는 복원하면 안 됩니다): {rollback}")
    print()
    print("끝났습니다. 이어서:")
    print("  - 새 복구 암호 종이를 보관하고 옛 종이는 폐기하세요. 이전에 만든 옛 헤더 백업은 이제 무효이니 지우세요.")
    print("  - 옛 FIDO2·TPM 슬롯과 토큰은 지워졌습니다. FIDO2 보안 키를 다시 쓰려면(이 ISO 에서도, 설치된 시스템에서도 가능):")
    print(f"      sudo systemd-cryptenroll --fido2-device=auto --fido2-with-client-pin=yes --fido2-with-user-presence=yes {dev}")
    print("    (새 복구 암호를 입력하고 키의 PIN 과 터치. 그 장치로 부팅 때 풀리려면 호스트 설정의 luks.fido2 가 켜져 있어야 함)")


RESEAL_HELP = """nixseal luks reseal — LUKS 마스터키 교체(사고 때 「전부 엎기」)

언제:   TPM 이 의도하지 않게 깨졌거나 변조·유출이 의심될 때. 평소 쓰는 명령이 아니다.
준비:   신뢰 USB(NixOS ISO)로 부팅한 ISO 안에서만 한다(설치된 시스템에서는 장치가 열려 있어 거부된다).
        **디스크 안에만 있는 소중한 데이터를 먼저 디스크 밖에 백업(이 명령의 전제 — 시작 전에 확인을 묻는다)** · 충전기 연결(안 되어 있으면 경고만) · 백업을 둘 USB 를 마운트(RAM 디스크 /tmp 는 거부) · 종이와 펜 · 현재 복구 암호(8단어).
실행:   sudo nixseal luks reseal --backup-dir <마운트한 USB 경로> /dev/disk/by-partlabel/cryptroot
순서:   1) 현재 복구 암호 입력  2) 새 8단어 + QR 표시 → 종이에 적고 Enter(화면이 지워짐) → 종이를 보고 다시 입력(3번 틀리면 중단)
        3) 대상 장치 정보 확인 후 장치 경로를 직접 입력  4) 되돌림용 헤더 백업  5) 새 암호 슬롯 추가·열림 확인  6) reencrypt(오래 걸림)
        7) 새 암호 열림 확인 · 옛 FIDO2/TPM 토큰 정리 · 초기 상태 헤더 백업 하나만 남김. 1~3 단계에서 멈추면 디스크는 그대로다.
끝난 뒤: 새 종이 보관 · 옛 종이 폐기 · 옛 헤더 백업은 무효이니 삭제 · 설치된 시스템에서 새 복구 암호로 부팅한 뒤 FIDO2/TPM 을 다시 등록(슬롯이 전부 지워졌다).
멈췄을 때(정전·실수로 끔·오류):
        헤더 백업을 복원하지 말고 같은 장치로 이어서 끝낸다:
        sudo nixseal luks reseal --backup-dir <USB> --resume /dev/disk/by-partlabel/cryptroot   (새 복구 암호 필요)
하면 안 되는 것:
        - reencrypt 를 시작한 뒤에 옛(또는 되돌림용) 헤더 백업을 복원하지 않는다 — 데이터가 깨진다(시험에서 확인). 백업은 「시작 전에 실패」했을 때만 쓴다.
        - 새 복구 암호를 종이에 적기 전에 Enter 를 누르지 않는다(그 화면은 다시 볼 수 없다).
        - 도중에 전원을 끄거나 충전기를 빼지 않는다. ssh 로 하지 않는다(스크롤백에 암호가 남는다).
        - 소중한 데이터를 디스크 밖에 백업하지 않은 채 시작하지 않는다 — 정전·강제 종료가 reencrypt 후반부에 일어나면 복구하지 못하고 디스크가 잠길 수 있다(VM 시험에서 재현; 앞쪽에서 끊긴 경우는 --resume 으로 복구됨).
        - 설치된 시스템 위에서 하려고 우회하지 않는다(거부되는 것이 정상이다).
문서:   저장소 hosts/msi-summit-me/SECURE-BOOT.md §2-12 (같은 내용 + 시험한 범위·못 한 범위)
"""


def cmd_luks_reseal(args):
    if any(a in ("--help", "-h") for a in args):
        print(RESEAL_HELP)
        return
    _need_root(["luks", "reseal"] + args)
    args = list(args)
    backup_dir, resume, force_offline, allow_tmpfs = None, False, False, False
    if "--backup-dir" in args:
        i = args.index("--backup-dir")
        if i + 1 >= len(args):
            _die("--backup-dir 에 디렉터리가 필요합니다", 2)
        backup_dir = args[i + 1]
        del args[i:i + 2]
    if "--resume" in args:
        resume = True
        args.remove("--resume")
    if "--force-offline" in args:
        force_offline = True
        args.remove("--force-offline")
    if "--allow-tmpfs" in args:
        allow_tmpfs = True
        args.remove("--allow-tmpfs")
    if len(args) != 1 or not backup_dir:
        _die("사용: nixseal luks reseal --backup-dir <디렉터리> <장치>   |   nixseal luks reseal --backup-dir <디렉터리> --resume <장치>", 2)
    dev = args[0]
    # ── 1. 사전 점검(디스크 불변) ──
    if _cs(["isLuks", dev]).returncode != 0 or not _is_luks2(dev):
        _die(f"{dev}: LUKS2 장치가 아닙니다")
    if not os.path.isdir(backup_dir) or not os.access(backup_dir, os.W_OK):
        _die(f"--backup-dir 이 없거나 쓸 수 없습니다: {backup_dir}")
    if _fstype(backup_dir) in ("tmpfs", "ramfs") and not allow_tmpfs:
        _die(f"--backup-dir {backup_dir} 는 RAM 디스크(tmpfs)라 재부팅하면 백업이 사라집니다. USB 같은 실제 저장 매체를 마운트해 그 경로를 주세요(정말 필요하면 --allow-tmpfs)")
    if _is_open(dev):
        _die(f"{dev} 가 열려 있습니다(매퍼 존재). 설치된 시스템 위에서는 마스터키를 바꾸지 않습니다 — 신뢰 USB(ISO)로 부팅해 닫힌 상태에서 하세요")
    ac = _on_ac_power()
    pct = _battery_percent()
    if ac is False:
        print("경고: AC 전원이 연결돼 있지 않습니다(배터리만). 충전기를 연결하세요 — 도중에 전원이 끊기면 데이터를 잃을 수 있고, 그 대비는 디스크 밖 백업뿐입니다.")
    elif ac is True and pct is not None and pct < 50:
        print(f"경고: 배터리 잔량이 {pct}% 입니다. 충전기가 빠지면 위험하니 충전 상태를 확인하세요.")
    elif ac is None:
        print("주의: 전원 상태를 알 수 없습니다(전원 정보 없음).")
    if resume:
        print("== 이어서 끝내기 ==")
        pw = _normalize(_ask_secret("새 복구 암호(reseal 에서 만든 것): "))
        _repair(dev, pw)  # 정전 뒤라면 필요(아니면 무해)
        rc = _run_reencrypt(dev, pw, None, True, force_offline)
        if rc != 0:
            _die(f"이어서 하기 실패(rc={rc}). 헤더 백업을 복원하지 마세요. 같은 명령을 다시 실행하거나 상황을 확인하세요")
        _finish_reseal(dev, pw, backup_dir, None)
        return
    slots, tokens = _slot_numbers(dev)
    print("== LUKS 마스터키 교체(reseal) ==")
    print(f"장치: {dev}   현재 키슬롯 {sorted(slots)}, 토큰 {[t[1] for t in tokens] or '없음'}")
    print("하는 일: 새 복구 암호(8단어)를 만들고, 디스크 전체를 새 마스터키로 다시 암호화합니다. 데이터는 그대로 남지만")
    print("  - 옛 암호·FIDO2·TPM 슬롯은 모두 사라집니다(끝난 뒤 새 복구 암호로 열고 다시 등록).")
    print("  - 디스크 크기에 비례해 오래 걸립니다. 충전기를 빼지 말고 도중에 끄지 마세요.")
    print(f"  - 중단되면 같은 장치에 대해: nixseal luks reseal --backup-dir {backup_dir} --resume {dev}  (헤더 백업을 복원하지 마세요)")
    print()
    # ── 2. 현재 암호 확인 → 새 복구 암호 생성·종이 확인(디스크 불변) ──
    old_pw = _ask_current_passphrase(dev)
    new_pw = _record_new_passphrase(dev)
    # ── 3. 장치 경로 확인 ──
    print()
    print("[왜 묻나] 디스크 전체를 다시 암호화하는 동안 정전·강제 종료가 나면 복구 수단이 없을 수 있어, 디스크 밖 백업이 유일한 보험입니다.")
    print("※ 정전·강제 종료가 reencrypt 의 후반부에 일어나면 cryptsetup 으로도 복구하지 못하고 디스크가 잠길 수 있다(2026-11-19 VM 시험에서 재현).")
    print("  그래서 이 디스크 안에만 있는 소중한 데이터는 먼저 디스크 밖에 백업해 두어야 한다. 앞쪽에서 끊긴 경우는 --resume 으로 이어서 끝난다.")
    if _ask(f"소중한 데이터를 디스크 밖에 백업해 두었습니까? 계속하려면 '{BACKUP_ACK}' 를 그대로 입력하세요: ") != BACKUP_ACK:
        _die("백업 확인이 없어 중단합니다(디스크는 변경되지 않았습니다)")
    info = subprocess.run(["lsblk", "-o", "NAME,SIZE,MODEL,FSTYPE,LABEL", dev], capture_output=True, text=True).stdout
    if info.strip():
        print("대상 장치:\n" + "\n".join("    " + ln for ln in info.splitlines()))
    typed = _ask(f"디스크의 모든 데이터를 새 키로 다시 암호화합니다. 계속하려면 장치 경로 '{dev}' 를 그대로 입력하세요: ")
    if typed != dev:
        _die("입력이 일치하지 않아 중단합니다(디스크는 변경되지 않았습니다)")
    # ── 4. 되돌림용 헤더 백업(reencrypt 를 시작하기 전에 실패했을 때만 쓴다) ──
    rollback = do_backup(dev, backup_dir, "reseal-rollback")
    print(f"되돌림용 헤더 백업: {rollback}  (※ reencrypt 를 시작한 뒤에는 복원하면 데이터가 깨집니다 — 시작 전에 실패했을 때만 쓰세요)")
    # ── 5. 새 슬롯 추가·열림 확인(옛 슬롯 그대로) ──
    slot = _add_slot(dev, old_pw, new_pw)
    old_pw = ""
    if not _pw_opens(dev, new_pw):
        _die(f"새 슬롯({slot})이 새 복구 암호로 열리지 않습니다 — reencrypt 하지 않고 중단합니다. 옛 슬롯은 그대로이니 평소처럼 열립니다")
    print(f"새 복구 암호 슬롯 {slot} 추가·열림 확인 완료. 이제 reencrypt 를 시작합니다(다른 슬롯은 끝나면 사라집니다).")
    # ── 6. reencrypt ──
    rc = _run_reencrypt(dev, new_pw, slot, False, force_offline)
    if rc != 0:
        print(f"reencrypt 가 비정상 종료했습니다(rc={rc}). 데이터는 이어서 끝낼 수 있습니다:", file=sys.stderr)
        print(f"  nixseal luks reseal --backup-dir {backup_dir} --resume {dev}   (새 복구 암호 필요; 헤더 백업은 복원하지 마세요)", file=sys.stderr)
        sys.exit(rc or 1)
    _finish_reseal(dev, new_pw, backup_dir, rollback)


# ───────────────────────── status · 진입점 ─────────────────────────

def cmd_status(args):
    _need_root(["status"] + args)
    sb_status(full=shutil.which(SBCTL) is not None)
    print()
    print("== LUKS 슬롯 ==")
    dev = args[0] if args else (CRYPTROOT if os.path.exists(CRYPTROOT) else "")
    if not dev:
        print(f"장치를 찾지 못함({CRYPTROOT} 없음) — nixseal status <장치> 또는 nixseal luks slots <장치>")
        return
    print(f"장치: {dev}")
    print_slots(dev)


# ───────────────────────── 복구 (recover, ISO 전용) ─────────────────────────
# 계획: ctx plan/nixseal-recover. 신뢰 USB(ISO)에서 의심스러운 ESP 를 증거로 남기고, 같은 라벨·볼륨 ID 로 포맷한 뒤 루트의 서명 키로 다시 만든다.
# TPM 은 건드리지 않는다(ISO 는 Secure Boot 를 끄고 부팅해 PCR 이 대상 시스템과 달라 정책을 갱신할 수 없다) — 첫 부팅 뒤 할 일을 안내만 한다.

MNT = os.environ.get("NIXSEAL_MNT", "/mnt")
RAM_FS = ("tmpfs", "ramfs", "overlay", "squashfs", "devtmpfs")
FORMAT_ACK = "포맷"
RECOVER_MAPPER = "cryptroot"   # fstab 의 장치 이름(/dev/mapper/cryptroot)과 같아야 마운트가 맞는다


def _x(name, args, capture=True, input_text=None):
    """외부 명령 실행(시험에서 바꿔 끼울 수 있는 한 지점). 못 찾으면 종료 코드 127 의 결과를 돌려준다(예외로 죽지 않음)."""
    exe = {"cryptsetup": CRYPTSETUP, "sbctl": SBCTL}.get(name) or os.environ.get("NIXSEAL_" + name.upper().replace("-", "_"), name)
    try:
        return subprocess.run([exe] + list(args), capture_output=capture, text=True, input=input_text)
    except OSError as e:
        return subprocess.CompletedProcess([exe] + list(args), 127, "", str(e))


def _in_iso():
    """ISO(RAM 위 루트)에서 실행 중인가 — 설치된 시스템에서 실수로 돌리지 않게. (판별 규칙은 ISO 에서 확인 필요: plan/nixseal-recover §8)"""
    return _x("findmnt", ["-no", "FSTYPE", "/"]).stdout.strip() in RAM_FS


def _fs_of(path):
    r = _x("findmnt", ["-no", "FSTYPE,SOURCE", "-T", path])
    parts = r.stdout.split()
    return (parts[0], parts[1] if len(parts) > 1 else "") if r.returncode == 0 and parts else ("", "")


def _blkid(dev):
    r = _x("blkid", ["-o", "export", dev])
    return dict(l.split("=", 1) for l in r.stdout.splitlines() if "=" in l) if r.returncode == 0 else {}


def _in_root(root, rel):
    """root 안의 rel 경로를 root 를 벗어나지 않게 심볼릭 링크까지 따라가 실제 경로로 돌려준다.
    NixOS 의 /etc/fstab 은 /etc/static/fstab 으로 가는 절대 링크라, 그냥 열면 ISO 쪽 경로를 가리켜 대상의 파일을 못 찾는다(VM 시험으로 확인)."""
    cur = os.path.join(root, rel.lstrip("/"))
    for _ in range(40):
        parts = os.path.relpath(cur, root).split(os.sep)
        for i in range(1, len(parts) + 1):
            part = os.path.join(root, *parts[:i])
            if os.path.islink(part):
                tgt = os.readlink(part)
                base = root if os.path.isabs(tgt) else os.path.dirname(part)
                cur = os.path.normpath(os.path.join(base, tgt.lstrip("/") if os.path.isabs(tgt) else tgt, *parts[i:]))
                if cur != root and not cur.startswith(root.rstrip("/") + "/"):
                    cur = os.path.join(root, os.path.relpath(cur, "/"))  # .. 로 밖으로 나가면 root 로 되돌린다
                break
        else:
            return cur
    return cur


def _parse_fstab(path):
    out = []
    try:
        with open(path) as f:
            for line in f:
                line = line.split("#")[0].strip()
                parts = line.split()
                if len(parts) >= 4:
                    out.append((parts[0], parts[1], parts[2], parts[3]))
    except OSError:
        pass
    return out


def _recover_b_branch():
    print("\n이상한 화면에 복구 암호나 FIDO2(PIN+터치)를 입력했을 수 있으면, 이 도구로 되돌릴 수 없는 것이 있습니다 —")
    print("부팅 파일 안에 백도어가 있었다면 이미 디스크 키가 새어 나갔을 수 있어 ESP 를 새로 만드는 것만으로는 부족합니다.")
    print("→ 「전부 엎기」(마스터키 교체 + 새 복구 암호 + 키 재등록)가 필요합니다: SECURE-BOOT.md §2-10, nixseal luks reseal --help")
    print("아무 것도 바꾸지 않고 멈춥니다.")


RECOVER_NEXT = """
== 이제 사람이 할 일 (자동으로 할 수 없음) ==
1. BIOS: Secure Boot Mode = Custom, Factory Default Key Provisioning = Disabled. 키가 지워졌으면 Setup Mode 에서
   `NIXSEAL_PKI=<대상>/var/lib/sbctl nixseal sb enroll` 로 다시 등록한 뒤 Secure Boot = Enabled. BIOS 관리자 암호를 설정(또는 재설정).
2. 첫 부팅은 **복구 암호**로 엽니다(TPM 은 이 ISO 에서 다시 맞출 수 없습니다).
3. 부팅된 시스템에서: `nixseal sb status` 로 확인 → TPM+PIN 을 쓰는 중이면
   · 상태(Secure Boot 키·dbx)가 그대로였다면 `nixseal tpm refresh-policy`(ESP 에 credential 이 없으면 자동으로 다시 씀)
   · 바뀌었다면(침해 의심 포함) `sudo systemd-pcrlock remove-policy` 후 `nixseal tpm enroll --replace`(PIN 은 새로 정하세요 — 노출됐을 수 있음)
4. 증거 tar 에서 nix 가 만들지 않는 것(Windows 의 EFI/Microsoft, EFI/nixos-iso, 사용자가 둔 rEFInd 드라이버 등)을 골라 되돌립니다.
5. 복구 매체·서명 키 백업이 그대로인지 확인.
"""


def _recover_cleanup(mapper_open):
    _x("umount", ["-R", MNT])
    if mapper_open:
        _x("cryptsetup", ["close", RECOVER_MAPPER])


def cmd_recover(args):
    """ISO 에서: 의심스러운 ESP → 증거 보관 → (같은 라벨·볼륨 ID 로) 포맷 → 서명 키로 재생성(또는 --from-backup) → NVRAM 확인 → 안내."""
    _need_root(["recover"] + args)
    root = os.environ.get("NIXSEAL_RECOVER_ROOT", CRYPTROOT)
    evid_dir, evidence, evid_image, from_backup, pki = None, True, False, None, "/var/lib/sbctl"
    it = iter(args)
    for a in it:
        if a == "--root":
            root = next(it, "")
        elif a == "--evidence-dir":
            evid_dir = next(it, "")
        elif a == "--no-evidence":
            evidence = False
        elif a == "--evidence-image":
            evid_image = True
        elif a == "--from-backup":
            from_backup = next(it, "")
        elif a == "--pki":
            pki = next(it, "")
        else:
            _die(f"알 수 없는 옵션: {a} (nixseal --help)", 2)
    if not _in_iso():
        _die("ISO(신뢰 USB)로 부팅한 환경이 아니다 — 설치된 시스템에서는 돌리지 않는다(실행 중인 시스템의 ESP 를 포맷하게 된다). 복구용 ISO 로 부팅해서 실행하세요.")
    if from_backup is not None:
        if not os.path.isfile(from_backup):
            _die(f"백업 tar 가 없다: {from_backup}", 2)
        if not os.path.basename(from_backup).startswith("esp-backup-"):
            _die("esp-backup-* 파일만 복원할 수 있다(esp-evidence-* 는 의심스러운 ESP 의 증거라 되돌리면 안 된다)", 2)
    if evidence:
        if not evid_dir:
            _die("증거를 보관할 위치가 필요하다: --evidence-dir <USB 경로> (원치 않으면 --no-evidence)", 2)
        if not os.path.isdir(evid_dir):
            _die(f"증거 경로가 디렉터리가 아니다: {evid_dir}", 2)
        fst, _src = _fs_of(evid_dir)
        if not fst or fst in RAM_FS:
            _die(f"증거 경로가 저장 매체가 아니다({fst or '알 수 없음'}) — RAM 에 두면 재부팅하면 사라진다. USB 를 마운트해 그 경로를 주세요")
    if _x("cryptsetup", ["status", RECOVER_MAPPER]).returncode == 0:
        _die(f"/dev/mapper/{RECOVER_MAPPER} 가 이미 열려 있다 — 상태를 알 수 없는 환경에서는 진행하지 않는다(닫고 다시)")

    # 2. 갈래 질문 — 복구 암호/FIDO2 를 입력했으면 이 도구로는 부족하다(PIN 은 세지 않는다: plan §7 #6)
    print("\n[왜 묻나] 가짜 부팅 화면(부팅 파일 변조)에 복구 암호나 FIDO2 PIN+터치를 입력했다면, 그 값이 공격자에게 넘어갔을 수 있습니다.")
    print("          그러면 ESP 를 새로 만들어도 디스크 키 자체가 노출된 것이라 부족하고, 마스터키 교체(전부 엎기)가 필요합니다.")
    print("          (TPM 의 PIN 은 TPM 이 있는 이 기기에서만 쓸 수 있어 여기서는 세지 않습니다. '모르겠음'은 안전한 쪽으로 보아 여기서 멈춥니다.)")
    ans = _ask("이상한 부팅 화면에 복구 암호(8단어)나 FIDO2 PIN+터치를 입력한 적이 있습니까? [예/아니오/모르겠음]: ").strip()
    if ans != "아니오":
        _recover_b_branch()
        sys.exit(3)

    # 3. 루트 열기·마운트(ESP 제외)
    print(f"\n루트를 엽니다: {root} → /dev/mapper/{RECOVER_MAPPER} (복구 암호 입력)")
    if _x("cryptsetup", ["open", root, RECOVER_MAPPER], capture=False).returncode != 0:
        _die("루트를 열지 못했다(암호 오류·장치 없음)")
    opened = True
    try:
        os.makedirs(MNT, exist_ok=True)
        r = _x("mount", ["-o", "subvol=@", f"/dev/mapper/{RECOVER_MAPPER}", MNT])
        if r.returncode != 0:
            _die(f"루트를 마운트하지 못했다: {r.stderr.strip()}")
        fstab = _parse_fstab(_in_root(MNT, "etc/fstab"))
        esp_entry = next((e for e in fstab if e[1] == "/boot"), None)
        if esp_entry is None:
            _die("대상의 /etc/fstab 에서 /boot(ESP) 항목을 찾지 못했다")
        for dev, mp, fstype, opts in sorted(fstab, key=lambda e: e[1].count("/")):
            if mp in ("/", "/boot") or fstype in ("swap", "vfat") or mp == "none":
                continue
            _x("mount", ["--mkdir", "-o", opts, dev, MNT + mp])
        if not os.path.exists(os.path.join(MNT, "etc/NIXOS")):
            _die("대상이 NixOS 루트가 아니다(/etc/NIXOS 없음) — ESP 는 건드리지 않았다")
        key = _in_root(MNT, os.path.join(pki, "keys/db/db.key"))
        if from_backup is None and not os.path.exists(key):
            _die(f"서명 키가 없다({key}) — 재생성할 수 없다. ESP 는 건드리지 않았다. 키 백업에서 되돌리거나(SECURE-BOOT.md §2-6) --from-backup 으로 esp-backup 을 지정하세요")

        # 4. ESP 장치 확정(읽기 전용으로 마운트)
        esp_dev = os.path.realpath(esp_entry[0]) if os.path.exists(esp_entry[0]) else esp_entry[0]
        info = _blkid(esp_dev)
        if info.get("TYPE") != "vfat":
            _die(f"fstab 의 ESP 장치({esp_entry[0]} → {esp_dev})가 vfat 이 아니다({info.get('TYPE') or '읽지 못함'}) — 건드리지 않았다")
        fst_ev, src_ev = _fs_of(evid_dir) if evid_dir else ("", "")
        if evid_dir and os.path.realpath(src_ev) == esp_dev:
            _die("증거 경로가 ESP 와 같은 장치다 — 다른 USB 를 쓰세요")
        print("\nESP 로 보이는 장치:")
        print(_x("lsblk", ["-o", "NAME,SIZE,FSTYPE,LABEL,UUID,MOUNTPOINT", esp_dev]).stdout)
        print("[왜 확인하나] 이 단계 뒤에 이 장치를 통째로 포맷합니다. 장치 이름이 USB 등 다른 디스크를 가리키는 실수를 막으려고 경로를 직접 치게 합니다.")
        if _ask(f"이 장치가 이 기기의 ESP 가 맞으면 장치 경로를 그대로 입력하세요 ({esp_dev}): ").strip() != esp_dev:
            print("취소 — 아무 것도 바꾸지 않았습니다.", file=sys.stderr)
            sys.exit(1)
        os.makedirs(os.path.join(MNT, "boot"), exist_ok=True)
        if _x("mount", ["-t", "vfat", "-o", "ro,nodev,nosuid,noexec,fmask=0137,dmask=0027", esp_dev, os.path.join(MNT, "boot")]).returncode != 0:
            _die("ESP 를 읽기 전용으로 마운트하지 못했다(파일시스템이 심하게 손상됐을 수 있음) — 건드리지 않았다")

        # 5. 증거 보관(실패하면 중단 — ESP 는 그대로)
        if evidence:
            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            tar_path = os.path.join(evid_dir, f"esp-evidence-{stamp}.tar")
            rt = _x("tar", ["-C", os.path.join(MNT, "boot"), "-cf", tar_path, "."])
            if rt.returncode != 0 or not os.path.exists(tar_path) or os.path.getsize(tar_path) == 0:
                _die(f"증거 tar 를 저장하지 못했다(tar 종료 {rt.returncode}: {(rt.stderr or '').strip()[:300]}) — ESP 는 그대로 둔다")
            if _x("tar", ["-tf", tar_path]).returncode != 0:
                _die("저장한 증거 tar 를 읽을 수 없다 — ESP 는 그대로 둔다")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    sb_status(full=shutil.which(SBCTL) is not None)
                except Exception as e:  # 증거 수집 실패가 복구를 막지는 않는다
                    print(f"(nixseal status 실패: {e})")
            meta = (f"# esp-evidence {stamp}\n# 포맷 전 ESP 의 라벨·볼륨 ID(같은 값으로 다시 포맷한다)\n"
                    f"device={esp_dev}\nLABEL={info.get('LABEL', '')}\nUUID={info.get('UUID', '')}\n\n"
                    f"== efibootmgr -v ==\n{_x('efibootmgr', ['-v']).stdout}\n== nixseal status ==\n{buf.getvalue()}\n"
                    f"== lsblk ==\n{_x('lsblk', ['-o', 'NAME,SIZE,FSTYPE,LABEL,UUID,PARTUUID,MOUNTPOINT']).stdout}\n")
            with open(os.path.join(evid_dir, f"esp-evidence-{stamp}.txt"), "w") as f:
                f.write(meta)
            if evid_image:
                size = int((_x("blockdev", ["--getsize64", esp_dev]).stdout or "0").strip() or 0)
                if size and shutil.disk_usage(evid_dir).free < size + (64 << 20):
                    _die("증거 이미지를 둘 USB 공간이 부족하다 — --evidence-image 를 빼거나 큰 USB 를 쓰세요(ESP 는 그대로)")
                if _x("dd", [f"if={esp_dev}", f"of={os.path.join(evid_dir, f'esp-evidence-{stamp}.img')}", "bs=4M", "conv=fsync", "status=none"]).returncode != 0:
                    _die("증거 이미지를 저장하지 못했다 — ESP 는 그대로 둔다")
            print(f"증거 저장: {tar_path} (+ .txt{', .img' if evid_image else ''})")
        label, volid = info.get("LABEL", ""), info.get("UUID", "").replace("-", "")

        # 6. 포맷 — 되돌릴 수 없다. 같은 라벨·볼륨 ID(fstab 의 UUID 마운트 유지), 파티션 GUID 는 GPT 라 그대로(UEFI 항목 유지)
        print(f"\nESP({esp_dev})를 포맷합니다 — 내용만 지우면 조작된 FAT 구조가 남을 수 있어서입니다. 라벨 '{label}'·볼륨 ID {info.get('UUID', '')} 는 유지합니다.")
        print("[왜 확인하나] 포맷하면 ESP 의 모든 파일(Windows 부팅 항목 등 nix 가 만들지 않은 것 포함)이 사라집니다. 방금 저장한 증거 tar 에서만 꺼낼 수 있습니다." if evidence else "[왜 확인하나] 포맷하면 ESP 의 모든 파일이 사라지고, --no-evidence 로 증거를 남기지 않았으므로 되돌릴 방법이 없습니다.")
        if _ask(f"되돌릴 수 없습니다. 계속하려면 '{FORMAT_ACK}' 를 입력하세요: ").strip() != FORMAT_ACK:
            print("취소 — 포맷하지 않았습니다.", file=sys.stderr)
            sys.exit(1)
        boot = os.path.join(MNT, "boot")
        if _x("umount", [boot]).returncode != 0:
            _die("ESP 를 내리지 못했다 — 포맷하지 않았다")
        if _x("mountpoint", ["-q", boot]).returncode == 0:
            _die("ESP 가 아직 마운트돼 있다 — 포맷하지 않았다")
        mk = ["-F", "32"] + (["-n", label] if label else []) + (["-i", volid] if volid else []) + [esp_dev]
        if _x("mkfs.vfat", mk).returncode != 0:
            _die("mkfs.vfat 실패 — ESP 가 비어 있거나 반쯤 만들어졌을 수 있다. 같은 명령으로 다시 시도하세요(증거는 저장됨)")
        if _x("mount", ["-t", "vfat", "-o", "nodev,nosuid,noexec,fmask=0077,dmask=0077", esp_dev, boot]).returncode != 0 or _x("mountpoint", ["-q", boot]).returncode != 0:
            _die("새 ESP 를 마운트하지 못했다")

        # 7. 재생성 또는 지정한 백업 복원
        if from_backup is not None:
            if _x("tar", ["-xf", from_backup, "-C", boot, "--no-same-owner"]).returncode != 0:
                _die("백업 복원 실패 — ESP 는 비어 있다. 다시 시도하세요")
            print(f"백업을 복원했습니다: {from_backup} (오래됐을 수 있습니다 — 신뢰는 직접 판단하세요)")
        else:
            r = _x("nixos-enter", ["--root", MNT, "-c", "/nix/var/nix/profiles/system/bin/switch-to-configuration boot"], capture=False)
            if r.returncode != 0:
                print("\n재생성에 실패했습니다. ESP 는 비어 있습니다(루트·서명 키는 그대로).", file=sys.stderr)
                print("→ 원인을 고쳐 다시 실행하거나, 오래돼도 괜찮다면 지정해 복원: nixseal recover --from-backup <esp-backup-*.tar> [--evidence-dir …]", file=sys.stderr)
                sys.exit(1)

        # 8. 검증·NVRAM
        rv = _x("nixos-enter", ["--root", MNT, "-c", "sbctl verify"])
        print("\n== sbctl verify ==\n" + (rv.stdout or rv.stderr or "(출력 없음)"))
        uki = glob.glob(os.path.join(boot, "EFI/Linux/*.efi"))
        if not uki:
            print("경고: ESP 에 UKI(EFI/Linux/*.efi)가 없다 — 이대로는 부팅되지 않을 수 있다", file=sys.stderr)
        print("== efibootmgr -v ==\n" + _x("efibootmgr", ["-v"]).stdout)
        print("rEFInd 항목이 없거나 BootOrder 가 이상하면 SECURE-BOOT.md §2-1 의 efibootmgr 절차로 등록하세요(낯선 항목은 직접 확인 후 삭제 — 이 도구는 지우지 않습니다).")
        print(RECOVER_NEXT)
    finally:
        _recover_cleanup(opened)


TPM = {"status": cmd_tpm_status, "enroll": cmd_tpm_enroll, "refresh-policy": cmd_tpm_refresh_policy}
SB = {"status": cmd_sb_status, "verify": cmd_sb_verify, "backup-esp": cmd_sb_backup_esp, "enroll": cmd_sb_enroll, "dbx": cmd_sb_dbx, "dbx-update": cmd_sb_dbx_update}
LUKS = {"slots": cmd_luks_slots, "backup": cmd_luks_backup, "verify": cmd_luks_verify, "restore": cmd_luks_restore, "reseal": cmd_luks_reseal}


# ───────────────────────── 봉인된 로그인 비밀번호 (pw) ─────────────────────────
# 계획: ctx plan/boot-doctor-keyring §11-B. 계정 비밀번호 P 를 TPM 에 봉인한다(인증값 = SHA-256(부팅 PIN)). 부팅 직후 root 서비스(core/lib/tpm-login.nix)가
# 캐시된 부팅 PIN 으로 P 를 풀어 PAM 에 준다 — 부팅 PIN 자체는 로그인 비밀번호로 쓰이지 않는다. 비밀(PIN·P)은 명령줄·환경변수에 넣지 않고 stdin·0600 임시 파일로만 다룬다.

PWSEAL_DIR = os.environ.get("NIXSEAL_PWSEAL_DIR", "/var/lib/nixseal/pwseal")
TPMRM = os.environ.get("NIXSEAL_TPMRM", "/dev/tpmrm0")
SRK_ATTRS = "restricted|decrypt|fixedtpm|fixedparent|sensitivedataorigin|userwithauth|noda"   # 서비스(core/lib/tpm-login.nix)와 같은 부모 키 템플릿 — 같은 템플릿이면 결정적(VM 실험)
SEAL_ACK = "교체"
REMOVE_ACK = "삭제"


def _tpm(name, args, input_bytes=None):
    """tpm2-tools 실행(시험에서 바꿔 끼울 수 있는 한 지점). 못 찾으면 종료 코드 127 의 결과를 돌려준다."""
    exe = os.environ.get("NIXSEAL_" + name.upper(), name)
    env = dict(os.environ)
    env.setdefault("TPM2TOOLS_TCTI", "device:/dev/tpmrm0")
    try:
        return subprocess.run([exe] + list(args), input=input_bytes, capture_output=True, env=env)
    except OSError as e:
        return subprocess.CompletedProcess([exe] + list(args), 127, b"", str(e).encode())


def _pw_auth(pin):
    """TPM 인증값 = SHA-256(PIN): 길이·문자 제한을 없앤다(인증값은 해시 길이 32바이트가 상한 — VM 실험)."""
    return hashlib.sha256(pin.encode()).digest()


def _chkpwd(user, pw):
    """P 가 지금 그 계정의 비밀번호인지(unix_chkpwd). 확인 수단이 없으면 None."""
    exe = os.environ.get("NIXSEAL_UNIX_CHKPWD") or ("/run/wrappers/bin/unix_chkpwd" if os.path.exists("/run/wrappers/bin/unix_chkpwd") else shutil.which("unix_chkpwd"))
    if not exe:
        return None
    try:
        return subprocess.run([exe, user, "nullok"], input=pw.encode() + b"\0", capture_output=True).returncode == 0
    except OSError:
        return None


def _pw_paths(user):
    return os.path.join(PWSEAL_DIR, user + ".pub"), os.path.join(PWSEAL_DIR, user + ".priv"), os.path.join(PWSEAL_DIR, user + ".failed")


def _pw_user(args):
    """봉인 대상 계정: --user > nix 선언(NIXSEAL_DECL_TPMLOGIN) > sudo 를 부른 사용자."""
    user = None
    if "--user" in args:
        i = args.index("--user")
        user = args[i + 1] if i + 1 < len(args) else None
    user = user or os.environ.get("NIXSEAL_DECL_TPMLOGIN") or os.environ.get("SUDO_USER")
    if not user or user == "root":
        _die("봉인할 계정을 정할 수 없다 — --user <계정> 을 주세요", 2)
    try:
        pwd.getpwnam(user)
    except KeyError:
        _die(f"계정 {user} 이(가) 없다", 2)
    return user


def _pw_unseal(work, pub, priv, pin):
    """블롭을 로드하고 PIN 으로 푼다 → (rc, 비밀 또는 None, 오류 문자열). 서비스와 같은 순서(부모 키 → 로드 → 암호화 세션 → 해제)."""
    prim = os.path.join(work, "prim.ctx")
    r = _tpm("tpm2_createprimary", ["-C", "o", "-c", prim, "-G", "ecc256:aes128cfb", "-a", SRK_ATTRS])
    if r.returncode:
        return r.returncode, None, "TPM 의 부모 키를 만들지 못했다: " + r.stderr.decode(errors="replace").strip()[-200:]
    seal = os.path.join(work, "seal.ctx")
    r = _tpm("tpm2_load", ["-C", prim, "-u", pub, "-r", priv, "-c", seal])
    if r.returncode:
        return r.returncode, None, "봉인 블롭을 TPM 에 올리지 못했다(TPM 초기화나 블롭 손상): " + r.stderr.decode(errors="replace").strip()[-200:]
    sess = os.path.join(work, "sess.ctx")
    r = _tpm("tpm2_startauthsession", ["--hmac-session", "-S", sess])
    if r.returncode:
        return r.returncode, None, "TPM 암호화 세션을 만들지 못했다"
    out = os.path.join(work, "p.out")
    r = _tpm("tpm2_unseal", ["-c", seal, "-p", f"session:{sess}+file:-", "-o", out], input_bytes=_pw_auth(pin))
    _tpm("tpm2_flushcontext", [sess])
    if r.returncode:
        return r.returncode, None, r.stderr.decode(errors="replace")
    try:
        with open(out, "rb") as f:
            return 0, f.read().decode(), ""
    finally:
        with contextlib.suppress(OSError):
            os.remove(out)


def _pw_classify(err):
    if "authorization HMAC check failed" in err:
        return "bad-pin"
    if "DA lockout" in err:
        return "lockout"
    return "other"


def _pw_workdir():
    d = tempfile.mkdtemp(prefix="nixseal-pw.", dir="/run" if os.path.isdir("/run") and os.access("/run", os.W_OK) else None)
    os.chmod(d, 0o700)
    return d


def _pw_read_secrets(args, what_pin, what_pw, confirm_pw):
    """--stdin 이면 stdin 에서 PIN·P(각 한 줄), 아니면 숨겨 입력받는다."""
    if "--stdin" in args:
        lines = sys.stdin.read().split("\n")
        pin = lines[0] if lines else ""
        pw = lines[1] if len(lines) > 1 else ""
        return pin, pw
    pin = _ask_secret(what_pin)
    pw = _ask_secret(what_pw)
    if confirm_pw and _ask_secret("같은 계정 비밀번호를 한 번 더: ") != pw:
        _die("두 번 입력한 계정 비밀번호가 다르다 — 아무 것도 바꾸지 않았다")
    return pin, pw


def cmd_pw_seal(args):
    _need_root(["pw", "seal"] + args)
    user = _pw_user(args)
    if not os.path.exists(TPMRM):
        _die(f"TPM 장치({TPMRM})가 없다 — TPM2 가 켜진 기기에서만 쓸 수 있다")
    pub, priv, failed = _pw_paths(user)
    existing = os.path.exists(pub) or os.path.exists(priv)
    print(f"계정 {user} 의 비밀번호를 TPM 에 봉인합니다(부팅 PIN 으로 풀림).")
    print("   [왜] 부팅 때 입력하는 TPM PIN 을 로그인 비밀번호로 재사용하면 PIN 이 곧 계정 비밀번호가 되어 서로의 보호가 합쳐집니다.")
    print("   그래서 PIN 은 이 봉인을 푸는 열쇠로만 쓰고, 로그인에는 따로 정한 강한 계정 비밀번호가 쓰입니다. 계정 비밀번호는 지금 그대로이며 여전히 직접 입력해 로그인할 수 있습니다.")
    if existing and "--stdin" not in args:
        print("   이미 봉인이 있습니다 — 이 작업은 그것을 새 값으로 교체합니다.")
        if _ask(f"교체하려면 '{SEAL_ACK}' 를 그대로 입력하세요: ") != SEAL_ACK:
            print("취소 — 아무 것도 바꾸지 않았습니다.", file=sys.stderr)
            sys.exit(1)
    if "--stdin" not in args:
        print("   [왜] PIN 은 `nixseal tpm enroll` 때 정한 TPM PIN 과 **같아야** 합니다. 다르면 다음 부팅에서 해제가 실패하고 TPM 의 오입력 카운터(LUKS 의 TPM 해제와 공유)가 1 오릅니다.")
    pin, pw = _pw_read_secrets(args, "TPM PIN(부팅 때 입력하는 PIN): ", f"계정 {user} 의 비밀번호: ", True)
    if not pin or not pw:
        _die("PIN 과 계정 비밀번호는 비어 있을 수 없다 — 아무 것도 바꾸지 않았다")
    ok = _chkpwd(user, pw)
    if ok is None:
        _die("계정 비밀번호가 맞는지 확인할 수단(unix_chkpwd)이 없어 봉인하지 않았다")
    if not ok:
        _die(f"입력한 비밀번호가 계정 {user} 의 현재 비밀번호와 다르다 — 아무 것도 바꾸지 않았다(틀린 값을 봉인하면 부팅마다 로그인이 한 번 실패한다)")
    work = _pw_workdir()
    try:
        prim = os.path.join(work, "prim.ctx")
        r = _tpm("tpm2_createprimary", ["-C", "o", "-c", prim, "-G", "ecc256:aes128cfb", "-a", SRK_ATTRS])
        if r.returncode:
            _die("TPM 의 부모 키를 만들지 못했다: " + r.stderr.decode(errors="replace").strip()[-200:])
        pin_file = os.path.join(work, "p.in")
        fd = os.open(pin_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pw.encode())
        npub, npriv = os.path.join(work, "s.pub"), os.path.join(work, "s.priv")
        # 속성은 기본값(= 오입력 잠금 DA 켜짐)을 그대로 쓴다: -a 를 주면 기본이 통째로 대체된다(VM 실험)
        r = _tpm("tpm2_create", ["-C", prim, "-i", pin_file, "-p", "file:-", "-u", npub, "-r", npriv], input_bytes=_pw_auth(pin))
        with contextlib.suppress(OSError):
            os.remove(pin_file)
        if r.returncode:
            _die("TPM 에 봉인하지 못했다: " + r.stderr.decode(errors="replace").strip()[-200:])
        # 방금 만든 블롭이 이 PIN 으로 풀리는지 확인한다(성공은 오입력 카운터를 올리지 않는다)
        rc, got, err = _pw_unseal(work, npub, npriv, pin)
        if rc or got != pw:
            _die("봉인한 직후 풀어 보니 맞지 않는다 — 저장하지 않았다: " + (err.strip()[-200:] or "값 불일치"))
        os.makedirs(PWSEAL_DIR, mode=0o700, exist_ok=True)
        os.chmod(PWSEAL_DIR, 0o700)
        for src, dst in ((npub, pub), (npriv, priv)):
            tmp = dst + ".new"
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f, open(src, "rb") as g:
                f.write(g.read())
            os.replace(tmp, dst)
        with contextlib.suppress(OSError):
            os.remove(failed)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"봉인했습니다({pub}). 다음 부팅(TPM PIN 입력) 직후 로그인 화면에서 비밀번호를 묻지 않고 로그인되고 키링이 열립니다.")
    print("※ 키링의 비밀번호도 이 계정 비밀번호와 같아야 키링이 열립니다. TPM PIN 이나 계정 비밀번호를 바꾸면 이 명령을 다시 하세요.")


def cmd_pw_status(args):
    _need_root(["pw", "status"] + args)
    user = _pw_user(args)
    pub, priv, failed = _pw_paths(user)
    print(f"== 봉인된 로그인 비밀번호({user}) ==")
    print("블롭: " + ("있음" if os.path.exists(pub) and os.path.exists(priv) else "없음 — nixseal pw seal"))
    try:
        with open(failed) as f:
            mark = f.read().strip()
        print(f"실패 표지: {mark}")
        kind = mark.split()[0] if mark else ""
        if kind == "bad-pin":
            print("  지난 부팅에서 PIN 이 봉인할 때의 PIN 과 달라 풀지 못했습니다(TPM 오입력 카운터 +1). 같은 오입력을 반복하지 않으려고 이후 부팅은 시도하지 않습니다 → 현재 TPM PIN 으로 nixseal pw seal")
        elif kind == "stale":
            print("  봉인된 비밀번호가 지금의 계정 비밀번호와 다릅니다(비밀번호를 바꾼 뒤 갱신하지 않음) → nixseal pw seal")
    except OSError:
        print("실패 표지: 없음")


def cmd_pw_test(args):
    _need_root(["pw", "test"] + args)
    user = _pw_user(args)
    pub, priv, failed = _pw_paths(user)
    if not (os.path.exists(pub) and os.path.exists(priv)):
        _die("봉인이 없다 — nixseal pw seal")
    print("지금 TPM PIN 으로 봉인을 풀어 보고 계정 비밀번호와 맞는지 확인합니다(비밀번호는 출력하지 않습니다).")
    print("   [왜] 부팅 때까지 기다리지 않고 PIN·비밀번호가 맞는지 미리 확인하기 위해서입니다. 단 PIN 을 틀리게 입력하면 TPM 의 오입력 카운터가 1 오르며 LUKS 의 TPM 해제와 공유됩니다.")
    pin = _ask_secret("TPM PIN: ")
    work = _pw_workdir()
    try:
        rc, got, err = _pw_unseal(work, pub, priv, pin)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    if rc:
        kind = _pw_classify(err)
        if kind == "bad-pin":
            _die("PIN 이 봉인할 때의 PIN 과 다르다(TPM 오입력 카운터가 1 올랐다). 현재 TPM PIN 으로 nixseal pw seal 을 다시 하세요")
        if kind == "lockout":
            _die("TPM 이 오입력 잠금 상태다 — 잠시 뒤 다시 하거나 `sudo tpm2_dictionarylockout --clear-lockout`(TPM 소유자 확인 후)")
        _die("풀지 못했다: " + err.strip()[-200:])
    ok = _chkpwd(user, got)
    if ok is None:
        _die("풀었지만 계정 비밀번호와 맞는지 확인할 수단(unix_chkpwd)이 없다")
    if not ok:
        _die(f"풀렸지만 지금의 계정 {user} 비밀번호와 다르다(비밀번호를 바꾼 뒤 봉인을 갱신하지 않음) — nixseal pw seal")
    print("정상: PIN 으로 풀리고 계정 비밀번호와 일치합니다.")


def cmd_pw_remove(args):
    _need_root(["pw", "remove"] + args)
    user = _pw_user(args)
    pub, priv, failed = _pw_paths(user)
    found = [p for p in (pub, priv, failed) if os.path.exists(p)]
    if not found:
        print("봉인이 없다 — 지울 것이 없습니다.")
        return
    print(f"계정 {user} 의 봉인(블롭·표지)을 지웁니다: " + ", ".join(found))
    print("   [왜] 지워도 계정 비밀번호는 그대로이며 직접 입력해 로그인할 수 있습니다. 다만 부팅 직후 자동 로그인은 다시 봉인하기 전까지 되지 않습니다.")
    if "--yes" not in args and _ask(f"지우려면 '{REMOVE_ACK}' 를 그대로 입력하세요: ") != REMOVE_ACK:
        print("취소 — 아무 것도 바꾸지 않았습니다.", file=sys.stderr)
        sys.exit(1)
    for p in found:
        with contextlib.suppress(OSError):
            os.remove(p)
    print("지웠습니다.")


PW = {"seal": cmd_pw_seal, "status": cmd_pw_status, "test": cmd_pw_test, "remove": cmd_pw_remove}


# ───────────────────────── 선언 ↔ 실제 점검 (doctor) ─────────────────────────
# 계획: ctx plan/boot-doctor-keyring. nix 의 선언(luks·tpm2·fido2·secure-boot)과 실제 상태가 어긋나면 알린다. 읽기 전용 — 아무 것도 바꾸지 않는다.
# 판정(_judge)은 외부 명령 없이 돌아가는 순수 함수이고, 사실 수집(_gather_facts)만 명령·파일을 읽는다.
# 모든 FAIL·WARN·INFO 는 「원인 · → 할 일(명령) · → nix(수정 위치)」 형식이다(시험이 형식을 강제한다).

FP_FILE = os.environ.get("NIXSEAL_FP_FILE", "/var/lib/nixseal/sb-fingerprint")
ESP_MNT = os.environ.get("NIXSEAL_ESP_MNT", "/boot")


def _sb_fingerprint():
    """Secure Boot 변수(PK·KEK·db·dbx·SecureBoot·SetupMode)의 SHA-256 지문. 정책을 만든 시점과 지금이 같은지 비교하는 데 쓴다.
    (systemd-pcrlock predict 는 읽기 전용 비교에 쓸 수 없다 — plan/boot-doctor-keyring §11-A.) 읽지 못하면 None."""
    import hashlib
    h = hashlib.sha256()
    seen = False
    for name, guid in (("PK", G_GLOBAL), ("KEK", G_GLOBAL), ("db", G_DB), ("dbx", G_DB), ("SecureBoot", G_GLOBAL), ("SetupMode", G_GLOBAL)):
        try:
            with open(var_path(name, guid), "rb") as f:
                body = f.read()[4:]
            seen = True
        except FileNotFoundError:
            body = b"<absent>"
        except OSError:
            return None
        h.update(name.encode() + b"\0" + hashlib.sha256(body).digest())
    return h.hexdigest() if seen else None


def _record_fingerprint():
    """정책을 (다시) 만든 직후 그 시점의 Secure Boot 지문을 남긴다 — doctor 가 「정책 갱신 없이 상태가 바뀜」을 알아보게."""
    fp = _sb_fingerprint()
    if fp is None:
        return
    try:
        os.makedirs(os.path.dirname(FP_FILE), exist_ok=True)
        with open(FP_FILE, "w") as f:
            f.write(fp + "\n")
    except OSError as e:
        print(f"경고: Secure Boot 지문을 기록하지 못했다({e}) — doctor 가 정책 갱신 누락을 알리지 못합니다.", file=sys.stderr)


def _h(cause, do=None, nix=None):
    """doctor 메시지 형식: 원인 + 할 일(명령) + nix 수정 위치."""
    s = cause
    if do:
        s += "\n    → 할 일: " + do
    if nix:
        s += "\n    → nix: " + nix
    return s


def _decl():
    """래퍼가 환경변수로 준 선언. 값이 없으면 None(= 모름 → 그 칸은 건너뜀). luks 는 "" = 「luks 없음」 선언, "<이름>" = 선언."""
    e = os.environ

    def flag(k):
        v = e.get(k)
        return None if v is None else v == "1"

    return {"sb": flag("NIXSEAL_DECL_SB"), "tpm2": flag("NIXSEAL_DECL_TPM2"), "fido2": flag("NIXSEAL_DECL_FIDO2"),
            "luks": e.get("NIXSEAL_DECL_LUKS"), "luks_dev": e.get("NIXSEAL_DECL_LUKS_DEV") or None,
            "tplogin": e.get("NIXSEAL_DECL_TPMLOGIN")}   # 봉인 로그인 계정("" = 선언 없음, 없으면 모름)


def _dm_is_crypt(src):
    """장치가 dm-crypt(LUKS) 매퍼인가. 권한이 필요 없는 sysfs(/sys/class/block/dm-N/dm/uuid 의 「CRYPT-」 접두)로 본다 —
    cryptsetup status 는 비루트에서 권한 오류로 실패해 「암호화 아님」으로 오판했다(오탐 FAIL). 매퍼가 아니면 False, 읽지 못하면 None."""
    if not src.startswith("/dev/mapper/"):
        return False
    try:
        with open(f"/sys/class/block/{os.path.basename(os.path.realpath(src))}/dm/uuid") as fh:
            return fh.read().startswith("CRYPT-")
    except OSError:
        return None


def _gather_facts(decl):
    """실제 상태를 읽는다. 읽지 못한 항목은 None(= 확인하지 못함 — 「정상」으로 취급하지 않는다)."""
    f = {"root_src": None, "root_crypt": None, "sb_on": None, "setup_mode": None, "tokens": None, "policy_pcrs": None, "creds": None,
         "luks_dev": None, "policy_exists": False, "fp_now": None, "fp_saved": None, "is_root": os.geteuid() == 0}
    r = _x("findmnt", ["-no", "SOURCE", "--nofsroot", "/"])
    if r.returncode == 0 and r.stdout.strip():
        f["root_src"] = r.stdout.strip().splitlines()[0].strip()
        f["root_crypt"] = _dm_is_crypt(f["root_src"])
    f["sb_on"] = var_byte("SecureBoot", G_GLOBAL)
    f["setup_mode"] = var_byte("SetupMode", G_GLOBAL)
    dev = decl.get("luks_dev") if decl.get("luks_dev") and os.path.exists(decl["luks_dev"]) else _luks_dev([])
    f["luks_dev"] = dev or None
    if dev:
        try:
            d = _cs(["luksDump", dev])
            if d.returncode == 0:
                f["tokens"] = {k for _, k in parse_slots(d.stdout.decode(errors="replace"))["tokens"]}
        except OSError:
            pass
    f["policy_exists"] = os.path.exists(PCRLOCK_JSON)
    f["policy_pcrs"] = _pcrlock_pcrs()
    # ESP 가 마운트돼 있지 않으면 credential 이 「없다」가 아니라 「확인하지 못했다」
    f["creds"] = len(_esp_credentials()) if (os.path.ismount(ESP_MNT) or os.path.isdir(ESP_CRED_DIR)) else None
    tl = decl.get("tplogin")
    if tl is not None:
        users = [tl] if tl else sorted({os.path.basename(p)[:-4] for p in glob.glob(os.path.join(PWSEAL_DIR, "*.pub"))})
        f["pw"] = {}
        for u in users:
            pub, priv, failed = _pw_paths(u)
            mark = None
            try:
                with open(failed) as fh:
                    words = fh.read().split()
                mark = words[0] if words else "unknown"
            except OSError:
                pass
            f["pw"][u] = {"blob": os.path.exists(pub) and os.path.exists(priv), "mark": mark}
    f["fp_now"] = _sb_fingerprint()
    try:
        with open(FP_FILE) as fh:
            f["fp_saved"] = fh.read().strip() or None
    except OSError:
        pass
    return f


def _judge(decl, f):
    """(심각도, 메시지) 목록. 심각도: FAIL(다음 부팅이 깨지거나 보호가 조용히 빠짐) · WARN · INFO · OK. 선언이 None 인 칸은 판정하지 않는다."""
    out = []
    add = lambda sev, msg: out.append((sev, msg))
    root_hint = None if f.get("is_root", True) else "루트가 아니라 읽지 못했을 수 있다 — `sudo nixseal doctor`"
    # ── LUKS 루트 ──
    luks = decl.get("luks")
    if luks is not None:
        if f["root_src"] is None or f["root_crypt"] is None:
            add("INFO", _h("루트 장치가 암호화(dm-crypt)인지 확인하지 못했다(findmnt/sysfs 읽기 실패) — 암호화 여부를 비교하지 못함", do="`findmnt /` 와 `lsblk -f` 로 직접 확인"))
        elif luks:
            if f["root_crypt"]:
                add("OK", f"루트가 암호화 장치({f['root_src']}) 위에 있다(선언 luks={luks})")
            else:
                add("FAIL", _h(f"luks 를 선언했는데({luks}) 지금 루트({f['root_src']})는 암호화 장치가 아니다 — 재부팅하면 initrd 가 LUKS 장치를 열려다 실패해 부팅이 안 된다",
                               do="재부팅하지 말고 `lsblk -f` 로 루트가 LUKS 위인지 확인. 암호화 안 된 디스크라면 선언을 되돌리고 `nixup os`(암호화 디스크로 바꾸려면 재설치 — plan/boot-security S4)",
                               nix="hosts/<호스트>.toml 의 `luks = true` → `false`"))
        else:
            if f["root_crypt"]:
                add("FAIL", _h(f"luks 를 선언하지 않았는데 지금 루트({f['root_src']})가 암호화 장치다 — initrd 에 crypttab 이 없어 재부팅하면 루트를 열지 못한다",
                               do="재부팅하지 말고 선언을 켜고 `nixup os`",
                               nix="hosts/<호스트>.toml 의 `luks = true` (+ `mods.sys.services.luks.device` 가 실제 LUKS 파티션 경로인지)"))
            else:
                add("OK", "luks 선언 없음, 루트도 암호화되지 않음")
    # ── 슬롯(TPM2·FIDO2) ──
    tk = f["tokens"]
    if (decl.get("tpm2") is not None or decl.get("fido2") is not None) and luks != "":
        if tk is None:
            if not f["luks_dev"]:
                add("INFO", _h("LUKS 장치를 찾지 못했거나 둘 이상이라 하나로 정할 수 없어 TPM2·FIDO2 슬롯이 있는지 확인하지 못했다",
                               do="`lsblk -f` 로 LUKS 파티션을 확인", nix="`mods.sys.services.luks.device`(hosts/<호스트>.nix)가 실제 LUKS 파티션 경로인지"))
            else:
                add("INFO", _h(f"LUKS 헤더를 읽지 못해({f['luks_dev']}) TPM2·FIDO2 슬롯이 있는지 확인하지 못했다", do=root_hint or "`sudo cryptsetup luksDump " + f["luks_dev"] + "` 로 직접 확인"))
        else:
            has_tpm, has_fido = "systemd-tpm2" in tk, "systemd-fido2" in tk
            dev = f["luks_dev"] or "<장치>"
            if decl.get("tpm2") is True and not has_tpm:
                add("INFO", _h("tpm2 를 선언했지만 TPM2 슬롯이 아직 없다 — 지금은 복구 암호(또는 FIDO2)로 풀린다",
                               do="복구 암호로 연 상태에서 `sudo nixseal tpm enroll`(SECURE-BOOT.md §2-13)"))
            elif decl.get("tpm2") is False and has_tpm:
                add("WARN", _h("TPM2 슬롯이 있는데 tpm2 를 선언하지 않았다 — initrd 가 TPM 을 시도하지 않아 슬롯이 쓰이지 않는다(암호로만 풀림)",
                               do=f"쓸 거면 선언을 켜고 `nixup os` 후 재부팅, 안 쓸 거면 `sudo systemd-cryptenroll --wipe-slot=tpm2 {dev}`",
                               nix="hosts/<호스트>.nix 에 `mods.sys.services.luks.tpm2 = true`"))
            elif decl.get("tpm2") is True and has_tpm:
                pcrs, creds = f["policy_pcrs"], f["creds"]
                if pcrs is None:
                    add("FAIL", _h("TPM2 슬롯이 있는데 pcrlock 정책 파일을 읽지 못했다(/var/lib/systemd/pcrlock.json) — TPM 이 거부해 복구 암호로만 열린다",
                                   do="재부팅 전이면 `sudo nixseal tpm refresh-policy`. 이미 재부팅해 복구 암호로 열었다면 `sudo nixseal tpm enroll --replace`"))
                elif 7 not in pcrs:
                    add("FAIL", _h(f"TPM 정책이 PCR 7(Secure Boot 정책)을 보호하지 않는다(보호 PCR {pcrs}) — Secure Boot 변경을 TPM 이 감지하지 못한다(조용히 약해진 상태)",
                                   do="`mods.sys.services.luks.tpm2 = true` 인지 확인(initrd 측정 유닛이 따라 켜짐) → `nixup os` → 재부팅 → `sudo systemd-pcrlock remove-policy` → `sudo nixseal tpm enroll --replace`",
                                   nix="core/lib/luks-tpm2.nix 의 systemd-pcrphase-initrd·systemd-pcrosseparator(tpm2 선언이 켬)"))
                elif creds is None:
                    add("INFO", _h(f"ESP({ESP_MNT})가 마운트되어 있지 않아 정책 credential 이 있는지 확인하지 못했다", do=f"`sudo mount {ESP_MNT}` 후 다시 실행"))
                elif not creds:
                    add("FAIL", _h("ESP 에 pcrlock 정책 credential(loader/credentials/pcrlock.*.cred)이 없다 — 다음 부팅에서 TPM 이 「policy not found」로 거부한다",
                                   do="`sudo nixseal tpm refresh-policy`(credential 이 없으면 자동으로 --force)"))
                else:
                    add("OK", f"TPM2 슬롯 있음 · 정책이 PCR 7 을 보호(보호 PCR {pcrs}) · ESP 에 credential {creds}개")
                    if f.get("fp_now") is None:
                        add("INFO", _h("펌웨어 Secure Boot 변수를 읽지 못해 정책이 현재 상태와 맞는지 확인하지 못했다", do="UEFI 로 부팅했는지, `findmnt /sys/firmware/efi/efivars` 로 efivarfs 가 마운트돼 있는지 확인"))
                    elif f.get("fp_saved") is None:
                        add("INFO", _h("정책을 만든 시점의 Secure Boot 지문이 기록돼 있지 않아 정책 갱신 누락을 확인하지 못한다",
                                       do="지금 상태가 내가 아는 정상이라면 `sudo nixseal tpm refresh-policy`(지문이 기록됨)"))
                    elif f["fp_now"] != f["fp_saved"]:
                        add("FAIL", _h("정책을 마지막으로 만든 뒤 Secure Boot 키·dbx 가 바뀌었다 — 이대로 재부팅하면 TPM 이 거부한다",
                                       do="내가 직접 한 변경(dbx 갱신 등)이면 **재부팅 전에** `sudo nixseal tpm refresh-policy`. 기억에 없는 변경이면 복구 암호를 입력하지 말고 신뢰 USB 로 점검(SECURE-BOOT.md §2-10)"))
                    else:
                        add("OK", "정책을 만든 뒤 Secure Boot 키·dbx 가 바뀌지 않았다(지문 일치)")
            elif decl.get("tpm2") is False and not has_tpm:
                add("OK", "TPM2 선언 없음, 슬롯도 없음")
            if not has_tpm and f.get("policy_exists") and decl.get("tpm2") is not None:
                add("WARN", _h("pcrlock 정책(NV 인덱스)은 남아 있는데 TPM2 슬롯이 없다 — 쓰이지 않는 정책이 TPM 자리를 차지한다",
                               do="쓰지 않을 거면 `sudo systemd-pcrlock remove-policy`, 쓸 거면 `sudo nixseal tpm enroll`"))
            if decl.get("fido2") is True and not has_fido:
                add("INFO", _h("fido2 를 선언했지만 FIDO2 슬롯이 없다 — 암호로 풀린다", do=f"`sudo systemd-cryptenroll --fido2-device=auto {dev}`"))
            elif decl.get("fido2") is False and has_fido:
                add("INFO", _h("FIDO2 슬롯이 있고 fido2 선언은 꺼져 있다 — initrd 는 쓰지 않고 ISO 등에서만 쓸 수 있다(의도라면 정상)",
                               do="initrd 에서도 쓰려면 선언을 켜고 `nixup os`", nix="`mods.sys.services.luks.fido2 = true`"))
            elif decl.get("fido2") is True and has_fido:
                add("OK", "FIDO2 슬롯 있음(선언과 일치)")
    if decl.get("tpm2") and decl.get("fido2"):
        add("WARN", _h("tpm2 와 fido2 를 함께 켰다 — TPM 이 정책 불일치로 거부한 부팅에서도 FIDO2(PIN+터치)로 풀린다(체인 검사 우회)",
                       do="FIDO2 를 ISO 에서만 쓸 거면 선언을 끈다(슬롯은 헤더에 남아 ISO 에서 쓸 수 있다). 둘 다 쓸 거면 우회를 감수(SECURE-BOOT.md §2-10)",
                       nix="hosts/<호스트>.nix 의 `mods.sys.services.luks.fido2 = false`"))
    # ── 봉인된 로그인 비밀번호(tpm-login) ──
    tl = decl.get("tplogin")
    if tl is not None:
        pw = f.get("pw", {})
        if tl:
            s = pw.get(tl, {"blob": False, "mark": None})
            if not s["blob"]:
                add("INFO", _h(f"tpm-login 을 선언했지만 계정 {tl} 의 봉인된 비밀번호가 없다 — 지금은 평소처럼 비밀번호를 묻는다", do=f"`sudo nixseal pw seal --user {tl}`(현재 TPM PIN 과 계정 비밀번호가 필요)"))
            elif s["mark"] == "bad-pin":
                add("WARN", _h(f"지난 부팅에서 계정 {tl} 의 봉인된 비밀번호를 풀지 못했다 — 부팅 PIN 이 봉인할 때의 PIN 과 달랐다(TPM 오입력 카운터가 1 올랐고, 같은 오입력을 반복하지 않으려고 이후 부팅은 시도하지 않는다)",
                               do=f"현재 TPM PIN 으로 `sudo nixseal pw seal --user {tl}` 을 다시(PIN 을 바꿨다면 새 PIN 으로)"))
            elif s["mark"] == "stale":
                add("WARN", _h(f"계정 {tl} 의 봉인된 비밀번호가 지금의 계정 비밀번호와 다르다 — 계정 비밀번호를 바꾼 뒤 봉인을 갱신하지 않았다(자동 로그인이 되지 않는다)",
                               do=f"`sudo nixseal pw seal --user {tl}`"))
            elif s["mark"]:
                add("WARN", _h(f"계정 {tl} 의 봉인 해제가 지난 부팅에서 실패했다(표지: {s['mark']})", do=f"`sudo nixseal pw status --user {tl}` 로 확인하고 `sudo nixseal pw seal --user {tl}`"))
            else:
                add("OK", f"계정 {tl} 의 봉인된 비밀번호가 있고 지난 부팅의 실패 표지가 없다")
        else:
            left = [u for u, s in pw.items() if s["blob"]]
            if left:
                add("INFO", _h("봉인된 비밀번호가 남아 있는데 tpm-login 이 꺼져 있다 — 쓰이지 않는 봉인이다(" + ", ".join(left) + ")",
                               do="쓰지 않을 거면 `sudo nixseal pw remove --user <계정>`", nix="쓸 거면 `mods.sys.services.tpm-login.enable = true`(+ `user`)"))
    # ── Secure Boot ──
    if decl.get("sb") is not None:
        sb, sm = f["sb_on"], f["setup_mode"]
        if sb is None:
            add("INFO", _h("펌웨어 Secure Boot 상태를 읽지 못했다(UEFI 가 아니거나 efivarfs 없음)", do="UEFI 로 부팅했는지, `findmnt /sys/firmware/efi/efivars` 로 efivarfs 가 마운트돼 있는지 확인"))
        elif decl["sb"] and sb != 1:
            add("WARN", _h("secure-boot 를 선언했는데 펌웨어의 Secure Boot 가 꺼져 있다 — 부팅 파일은 서명되지만 아무도 검사하지 않는다(보호 없음)",
                           do="BIOS(F2/Del) → Secure Boot = Enabled 로 켠 뒤 `sudo nixseal sb status` 로 확인"))
        elif decl["sb"] and sm == 1:
            add("WARN", _h("secure-boot 를 선언했는데 펌웨어가 Setup Mode 다(키가 등록되지 않음) — 키를 등록해야 보호가 시작된다", do="`sudo nixseal sb enroll`"))
        elif decl["sb"]:
            add("OK", "펌웨어 Secure Boot 켜짐(User Mode) — 선언과 일치")
        elif sb == 1:
            add("FAIL", _h("secure-boot 를 선언하지 않았는데 펌웨어의 Secure Boot 가 켜져 있다 — 서명되지 않은 부팅 파일(systemd-boot)은 다음 부팅에서 Access Denied 로 거부된다",
                           do="재부팅하지 말고 선언을 켜고 `nixup os`(서명된 부팅 파일을 만든다). 급하면 BIOS 에서 Secure Boot 를 끄고 `sudo nixseal sb verify`",
                           nix="hosts/<호스트>.toml 의 `secure-boot = true`"))
        else:
            add("OK", "secure-boot 선언 없음, 펌웨어도 꺼져 있음")
    return out


def cmd_doctor(args):
    _need_root(["doctor"] + args)
    brief = "--brief" in args
    decl = _decl()
    if all(v is None for v in decl.values()):
        print("doctor: 선언 값이 없다(nix 래퍼 없이 실행) — 비교할 선언이 없어 점검하지 않았다.")
        return 0
    res = _judge(decl, _gather_facts(decl))
    shown = [r for r in res if not (brief and r[0] == "OK")]
    if shown:
        print("== nixseal doctor (선언 ↔ 실제) ==")
        for sev, msg in shown:
            print(f"[{sev}] {msg}")
    return 1 if any(s == "FAIL" for s, _ in res) else 0


def main(argv):
    if not argv or argv[0] in ("help", "-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "status":
        cmd_status(argv[1:])
        return 0
    if argv[0] == "recover":
        cmd_recover(argv[1:])
        return 0
    if argv[0] == "doctor":
        return cmd_doctor(argv[1:])
    group = {"sb": SB, "luks": LUKS, "tpm": TPM, "pw": PW}.get(argv[0])
    if group is not None and (len(argv) < 2 or argv[1] in ("help", "-h", "--help")):
        print(__doc__)
        return 0
    if group is None or argv[1] not in group:
        print(__doc__, file=sys.stderr)
        return 2
    group[argv[1]](argv[2:])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
